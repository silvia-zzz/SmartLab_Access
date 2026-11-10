import base64
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import msgpack
from algokit_utils import (
    AlgoAmount, AlgorandClient, AppClient, AppClientMethodCallParams,
    AppClientParams, PaymentParams,
)
from algokit_utils.transactions.transaction_sender import SendAppTransactionResult
from algosdk import abi, encoding, transaction
from algosdk.atomic_transaction_composer import TransactionSigner, TransactionWithSigner
from algosdk.error import AlgodHTTPError

from simulation.models import Lab, Request
from status_constants import (
    LAB_ACTIVE, 
    LAB_APPROVED, LAB_PENDING, REQ_PENDING, REQ_APPROVED, REQ_CONSUMED, REQ_REJECTED, REQ_REVOKED,
)

SPEC_PATH = (
    Path(__file__).resolve().parents[1]
    / "smart_contracts"/ "artifacts"/ "my_contract"/ "Access.arc56.json"
)

# Formato binario dei dati ocnservati nei box
LAB = abi.ABIType.from_string("(uint64,address,uint64,uint8,uint64,uint8)")
REQUEST = abi.ABIType.from_string(
    "(uint64,address,uint64,uint64,uint64,uint64,uint8,uint64,uint64)"
    )

MAX_FEE = 10000


class Client:
    """
    Gestisce la connessione al nodo Algorand e le chiamate allo smart contract.
    """
    def __init__(
        self,
        algorand: AlgorandClient,
        app_id: int,
        sender: str | None = None,
        signer: TransactionSigner | None = None,
    ) -> None:
        """
        Collega il client all'applicazione e all'eventuale firmatario.

        Input:
            algorand: client Algorand configurato per la rete
            app_id: ID dell'applicazione
            sender: indirizzo del mittente, opzionale
            signer: firmatario delle transazioni, opzionale
        """

        # Validazione dei parametri di inizializzazione
        if type(app_id) is not int or not 0 < app_id < 2**64:
            raise ValueError("ID applicazione non valido")
        if sender is not None and not encoding.is_valid_address(sender):
            raise ValueError("Indirizzo del mittente non valido")
        if signer is not None and sender is None:
            raise ValueError("Il firmatario richiede un mittente")
        if not SPEC_PATH.is_file():
            raise FileNotFoundError("Compilare il contratto prima di avviare il client")

        # Inizializzazione del client dell'applicazione
        self.algorand = algorand
        # Rilegge i round dal nodo anche dopo una lunga attesa nei menu.
        self.algorand.set_suggested_params_cache_timeout(0)

        # risorsa :https://dev.algorand.co/docs/algokit-utils/python/latest/concepts/core/algorand-client/#transaction-configuration
        # modifica su finestra di round
        self.algorand.set_default_validity_window(100)

        self.algod = algorand.client.algod
        self.app_id = app_id
        self.sender = sender
        self.signer = signer
        self._genesis: str | None = None
        app_params = AppClientParams(
                        app_spec=SPEC_PATH.read_text(encoding="utf-8"),
                        algorand=algorand,
                        app_id=app_id,
                        default_sender=sender,
                        default_signer=signer,
                    )
        self.app = AppClient(app_params)


    @property
    def genesis(self) -> str:
        """
        Identifica la rete del nodo collegato.

        Output:
            Hash genesis della rete.
        """

        # Caso in cui il nodo non ha ancora un identificativo nella rete.
        if self._genesis is None:
            value = self.algod.suggested_params().gh
            if isinstance(value, bytes):
                value = value.decode("ascii")
            if not isinstance(value, str) or len(base64.b64decode(value, validate=True)) != 32:
                raise ValueError("Identificativo della rete non valido")

            # Aggiornamento di hash gensis
            self._genesis = value
        return self._genesis


    def lab(self, lab_id: int) -> Lab:
        """
        Legge i dati del laboratorio dal relativo box.

        Input:
            lab_id: ID del laboratorio
        Output:
            Dati del laboratorio.
        """
        lab = Lab(*LAB.decode(self._box(b"l", lab_id)))
        if lab.id != lab_id:
            raise ValueError("Il box contiene un laboratorio diverso")
        return lab

    def system_admin(self) -> str:
        """
        Legge dal contratto l'account autorizzato a valutare le registrazioni.
        """
        info = self.algod.application_info(self.app_id)
        if not isinstance(info, dict) or not isinstance(info.get("params"), dict):
            raise ValueError("Stato dell'applicazione non valido")
        for entry in info["params"].get("global-state", []):
            if base64.b64decode(entry["key"], validate=True) != b"admin":
                continue
            value = entry["value"]

            if value.get("type") != 1:
                raise ValueError("Amministratore di sistema non valido")
            raw = base64.b64decode(value.get("bytes", ""), validate=True)

            if len(raw) != 32 or raw == bytes(32):
                raise ValueError("Amministratore di sistema non valido")
            return encoding.encode_address(raw)
        
        raise ValueError("Amministratore di sistema non disponibile")

    def labs(self, *, own: bool = False) -> Iterator[Lab]:
        """
        Elenca i laboratori senza presumere che i loro ID siano consecutivi.
        Con own=True seleziona quelli del mittente, in ogni stato di registrazione.

        Algod restituisce tutti i nomi oppure un errore se il limite del nodo
        viene superato: questo endpoint non supporta la paginazione.
        """
        sender = self._sender() if own else None
        response = self.algod.application_boxes(self.app_id, limit=0)
        if not isinstance(response, dict) or not isinstance(response.get("boxes"), list):
            raise ValueError("Elenco dei laboratori non valido")
        
        if response.get("next-token"):
            raise ValueError("Il nodo ha restituito un elenco incompleto dei laboratori")
        
        lab_ids: set[int] = set()
        
        for box in response["boxes"]:
            if not isinstance(box, dict) or not isinstance(box.get("name"), str):
                raise ValueError("Nome del box non valido")
            name = base64.b64decode(box["name"], validate=True)
            if len(name) == 9 and name[:1] == b"l":
                lab_ids.add(int.from_bytes(name[1:], "big"))

        for lab_id in sorted(lab_ids):
            lab = self.lab(lab_id)
            if not own or lab.admin == sender:
                yield lab

    def pending_labs(self) -> Iterator[Lab]:
        """
        Elenca le domande in attesa per la valutazione del sistema.
        """
        for lab in self.labs():
            if lab.registration == LAB_PENDING:
                yield lab

    def authorized_lab(self, lab_id: int) -> Lab:
        """
        Consente la gestione solo al titolare di un laboratorio approvato.
        """
        lab = self.lab(lab_id)
        if lab.admin != self._sender():
            raise ValueError("Amministratore non autorizzato per questo laboratorio.")
        if lab.registration != LAB_APPROVED:
            raise ValueError("Laboratorio non registrato.")
        return lab

    def req(self, req_id: int) -> Request:
        """
        Legge i dati della richiesta dal relativo box.

        Input:
            req_id: ID della richiesta
        Output:
            Dati della richiesta.
        """
        req = Request(*REQUEST.decode(self._box(b"r", req_id)))
        if req.id != req_id:
            raise ValueError("Il box contiene una richiesta diversa")
        return req


    def own(self, lab_id: int | None = None) -> Iterator[Request]:
        """
        Elenca tutte le richieste del mittente, con filtro facoltativo sul laboratorio.

        Input:
            lab_id: ID del laboratorio, oppure None per tutti i laboratori
        Output:
            Iteratore di oggetti Request appartenenti al mittente.
        """
        sender = self._sender()
        for req in self._requests():
            if req.user == sender and (lab_id is None or req.lab == lab_id):
                yield req

    def visible_requests(self) -> Iterator[Request]:
        """
        Elenca le proprie richieste e quelle dei laboratori approvati amministrati.
        
        Output:
            Lista delle richieste associate all'account richiedente
        """
        sender = self._sender()
        managed = {lab.id for lab in self.labs(own=True) if lab.registration == LAB_APPROVED}
        for req in self._requests():
            if req.user == sender or req.lab in managed:
                yield req

    def _requests(self) -> Iterator[Request]:
        """
        Legge tutt le richieste esistenti.
        
        Output:
            Restituisce lista delle richieste associate all'applicazione
        """
        info = self.algod.application_info(self.app_id)
        if not isinstance(info, dict):          # dict = dictionary
            raise ValueError("Risposta di algod.application_info non è un dizionario")
        state = info["params"].get("global-state", [])
        seq = None

        # Ricerca del contatore delle richieste nel global state dell'applicazione
        for entry in state:
            if base64.b64decode(entry["key"], validate=True) == b"seq":
                if entry["value"]["type"] != 2:     # 2 = intero
                    raise ValueError("Contatore delle richieste non valido")
                seq = entry["value"]["uint"]
                break

        # Verifica la validità del contatore trovato
        if not isinstance(seq, int) or not 0 <= seq < 2**64:
            raise ValueError("Contatore delle richieste non disponibile")

        for req_id in range(1, seq + 1):
            yield self.req(req_id)


    def access_request(self, lab_id: int) -> Request:
        """
        Trova la richiesta del mittente per ottenere o recuperare il PIN.
        
        Output:
            Richiesta autorizzzata
        """
        now = max(self.now(), int(time.time()))
        selected = None
        for req in self.own(lab_id):
            if req.status not in (REQ_APPROVED, REQ_CONSUMED):
                continue
            if not req.start <= now < req.end:
                continue
            if selected is not None:
                raise ValueError("Piu richieste valide per questo laboratorio: verificare le prenotazioni")
            selected = req
        if selected is None:
            raise ValueError("Nessuna richiesta autorizzata valida in questo momento per il laboratorio")
        return selected


    def now(self) -> int:
        """
        Legge il timestamp dell'ultimo blocco confermato.

        Output:
            Timestamp in secondi.
        """

        # Restituisce un dizionario Python con informazioni sullo stato del nodo.
        status = self.algod.status()
        if not isinstance(status, dict):
            raise ValueError("Risposta di algod.status() non è un dizionario")

        # Estrazione delle informazioni dell'ultimo blocco confermato
        info = self.algod.block_info(status["last-round"])
        if not isinstance(info, dict):
            raise ValueError("Risposta di algod.block_info non è un dizionario")
        
        block = info["block"]
        stamp = block["ts"]

        # Verifica la validità del timestamp estratto
        if not isinstance(stamp, int) or stamp <= 0:
            raise ValueError("Timestamp del blocco invalido")
        return stamp


    def confirm(self, txid: str) -> transaction.Transaction:
        """
        Verifica la conferma e ricostruisce la transazione.

        Input:
            txid: ID della transazione
        Output:
            Transazione confermata nel formato transaction.Transaction
        """

        # Controllo validità txid:
        # 1. Ogni stringa è una lettera maiuscola oppure una cifra da 2 a 7
        # 2. Ha esattamente 52 caratteri
        if not re.fullmatch(r"[A-Z2-7]{52}", txid):
            raise ValueError("Transaction ID non valido")

        # Recupero informazioni sulla transazione dal nodo
        raw = self.algod.pending_transaction_info(txid, response_format="msgpack")
        if not isinstance(raw, bytes):
            raise ValueError("Risposta data non è una sequenza di byte")

        # Conversione byte in dizionario Python
        info = msgpack.unpackb(raw, raw=False)      # False = converte tutti i byte in stringhe     
        if not isinstance(info, dict) or info.get("pool-error"):
            raise ValueError("Transazione rifiutata dal nodo")

        # Conferma che la transazione è stata inclusa in un blocco
        confirmed = info.get("confirmed-round", 0)
        if not isinstance(confirmed, int) or confirmed <= 0:
            raise ValueError("Transazione non confermata")

        # Ricostruzione della transazione dal info
        txn = transaction.Transaction.undictify(info["txn"]["txn"])
        if txn.get_txid() != txid:
            raise ValueError("La transazione non corrisponde al Transaction ID")
        if txn.genesis_hash != self.genesis:
            raise ValueError("La transazione appartiene a una rete diversa")
        if not txn.first_valid_round <= confirmed <= txn.last_valid_round:
            raise ValueError("Conferma fuori dall'intervallo della transazione")
        
        return txn


    def selector(self, name: str) -> bytes:
        """
        Ricava l'identificatore ABI di un metodo dello smart contract.

        Input:
            name: nome del metodo
        Output:
            Selettore ABI di 4 byte.
        """
        app_spec = self.app.app_spec

        # Ottenimento specifica del metodo dal contratto
        arc56_method = app_spec.get_arc56_method(name)

        # Conversione in ABI
        abi_method = arc56_method.to_abi_method()
        return abi_method.get_selector()


    def lab_cost(self) -> int:
        """
        Legge il deposito necessario per registrare un laboratorio.

        Output:
            Deposito in microAlgo.
        """
        return self._cost("lab_cost", [])

    def lock_cost(self) -> int:
        """Legge il deposito separato per l'associazione della serratura."""
        return self._cost("lock_cost", [])


    def req_cost(self, lab_id: int, start: int, end: int, user: str | None = None) -> int:
        """
        Legge il deposito necessario per una nuova richiesta.

        Input:
            lab_id: ID del laboratorio
            start: timestamp iniziale
            end: timestamp finale
            user: indirizzo dell'utente, oppure il mittente se non specificato
        Output:
            Deposito in microAlgo.
        """
        return self._cost("req_cost", [lab_id, user or self._sender(), start, end])


    def register_lab(self, lab_id: int) -> str:
        """
        Presenta una domanda di registrazione intestata al mittente.

        Input:
            lab_id: ID del laboratorio
        Output:
            Identificativo della transazione di registrazione.
        """
        if type(lab_id) is not int or not 0 < lab_id < 2**64:
            raise ValueError("ID laboratorio non valido: inserisci un intero positivo minore di 2^64")
        pay = self._payment(self.lab_cost())
        result = self._call("register_lab", [lab_id, pay])
        return result.tx_ids[-1]

    def review_lab(self, lab_id: int, approved: bool) -> str:
        """Approva o rifiuta una domanda attraverso l'account del sistema."""
        if type(approved) is not bool:
            raise ValueError("Esito della registrazione non valido")
        sender = self._sender()
        if sender != self.system_admin():
            raise ValueError("Account non autorizzato a valutare le registrazioni")
        lab = self.lab(lab_id)
        if lab.registration != LAB_PENDING:
            raise ValueError("La registrazione non e in attesa di valutazione")
        if lab.admin == sender:
            raise ValueError("Non puoi approvare o rifiutare la tua registrazione")
        return self._call("review_lab", [lab_id, approved]).tx_ids[-1]

    def register_lock(self, lab_id: int, lock_id: int) -> str:
        """Associa un ID di serratura univoco al laboratorio approvato del mittente."""
        if type(lock_id) is not int or not 0 < lock_id < 2**64:
            raise ValueError("ID serratura non valido: inserisci un intero positivo minore di 2^64")
        lab = self.authorized_lab(lab_id)
        if lab.lock_id != 0:
            raise ValueError("Il laboratorio ha gia una serratura")
        pay = self._payment(self.lock_cost())
        return self._call("register_lock", [lab_id, lock_id, pay]).tx_ids[-1]


    def request(self, lab_id: int, start: int, end: int) -> tuple[int, str]:
        """
        Aggiorna le proprie richieste scadute e crea una richiesta con il deposito esatto.

        Input:
            lab_id: ID del laboratorio
            start: timestamp iniziale
            end: timestamp finale
        Output:
            ID della richiesta e ID della transazione nel formato tuple[int, str].
        """

        # Controllo parametri input
        if any(type(value) is not int or not 0 <= value < 2**64 
               for value in (lab_id, start, end)):
            raise ValueError("Laboratorio e timestamp devono essere interi uint64")
        if end <= start or (end - start) % 3600 != 0:
            raise ValueError("La durata deve essere positiva e pari a un numero intero di ore")
        self._available(self.lab(lab_id))
        
        stamp = self.now()
        if start < stamp:
            raise ValueError("L'inizio della richiesta non puo essere nel passato")
        expired: list[int] = []

        # Verifica prenotazioni esistenti e richieste del mittente prima di inviare transazioni.
        sender = self._sender()
        for req in self._requests():
            if req.lab != lab_id:
                continue
            if req.status in (REQ_APPROVED, REQ_CONSUMED) and start < req.end and req.start < end:
                raise ValueError(
                    f"Il laboratorio e gia prenotato nell'intervallo scelto (richiesta {req.id})."
                )
            if req.user != sender:
                continue
            if req.status not in (REQ_PENDING, REQ_APPROVED):
                continue
            if req.start == start and req.end == end:
                raise ValueError("Esiste gia una richiesta aperta per intervallo inserito")
            if req.end <= stamp:
                expired.append(req.id)

        # Aggiornamento delle richieste scadute: APPEND => EXPIRED
        for req_id in expired:
            self.expire(req_id)

        if start < self.now():
            raise ValueError("L'inizio della richiesta invalido")

        # Pagamento della richiesta
        pay = self._payment(self.req_cost(lab_id, start, end))
        result = self._call("request", [lab_id, start, end, pay])
        if type(result.abi_return) is not int or not 0 < result.abi_return < 2**64:
            raise ValueError("Il contratto non ha restituito l'ID della richiesta")

        # Restituisce Transaction ID dell'ultima transazione
        return result.abi_return, result.tx_ids[-1]


    def approve(self, req_id: int) -> str:
        """
        Approva la richiesta indicando i vicini verificabili dal contratto.

        Input:
            req_id: ID della richiesta
        Output:
            ID della transazione di approvazione.
        """
        req = self.req(req_id)
        lab = self.authorized_lab(req.lab)
        self._available(lab)
        if req.status != REQ_PENDING:
            raise ValueError("Richiesta non in attesa")
        stamp = self.now()
        if stamp >= req.start:
            raise ValueError("Intervallo gia iniziato")
        prev_id, next_id = self._neighbors(req)
        if prev_id:
            previous = self.req(prev_id)
            if previous.end > req.start and previous.end > stamp:
                raise ValueError("Intervalli sovrapposti")
        if next_id and req.end > self.req(next_id).start:
            raise ValueError("Intervalli sovrapposti")
        return self._call("approve", [req_id, prev_id, next_id]).tx_ids[-1]

    def change_request_status(self, lab_id: int, req_id: int, new_status: int) -> str:
        """
        Modifica lo stato di una richiesta applicando solo le transizioni consentite.

        Input:
            lab_id: ID del laboratorio
            req_id: ID della richiesta
            new_status: nuovo stato della richiesta
        Output:
            Risultato dell'operazione di modifica dello stato
    """

        self.authorized_lab(lab_id)
        req = self.req(req_id)
        if req.lab != lab_id:
            raise ValueError("La richiesta appartiene a un altro laboratorio")
        if type(new_status) is not int:
            raise ValueError("Stato finale non valido")
        actions = {
            (REQ_PENDING, REQ_APPROVED): self.approve,
            (REQ_PENDING, REQ_REJECTED): self.reject,
            (REQ_APPROVED, REQ_REVOKED): self.revoke,
        }
        action = actions.get((req.status, new_status))
        if action is None:
            raise ValueError("Cambio di stato non consentito per questa richiesta")
        return action(req_id)


    def reject(self, req_id: int) -> str:
        """
        Rifiuta una richiesta ancora in attesa.

        Input:
            req_id: ID della richiesta
        Output:
            ID della transazione di rifiuto.
        """
        return self._call("reject", [req_id]).tx_ids[-1]


    def revoke(self, req_id: int) -> str:
        """
            Revoca una richiesta precedentemente approvata.

            Input:
                req_id: identificativo della richiesta
            Output:
                Identificativo della transazione di revoca.
        """
        return self._call("revoke", [req_id]).tx_ids[-1]


    def expire(self, req_id: int) -> str:
        """
            Aggiorna una propria richiesta scaduta dopo il controllo del contratto.

            Input:
                req_id: identificativo della richiesta
            Output:
                Identificativo della transazione di scadenza.
        """
        return self._call("expire", [req_id]).tx_ids[-1]


    def set_active(self, lab_id: int, active: bool) -> str:
        """
        Imposta lo stato operativo del laboratorio.

        Input:
            lab_id: ID del laboratorio
            active: True per attivare il laboratorio, False per disattivarlo
        Output:
            ID della transazione di aggiornamento.
        """
        if type(active) is not bool:
            raise ValueError("Stato operativo non valido")
        lab = self.authorized_lab(lab_id)
        if active and lab.lock_id == 0:
            raise ValueError("Registrare la serratura prima di attivare il laboratorio")
        return self._call("set_active", [lab_id, active]).tx_ids[-1]


    def use(self, req_id: int) -> str:
        """
        Consuma l'autorizzazione associata alla richiesta.

        Input:
            req_id: ID della richiesta
        Output:
            ID della transazione di utilizzo.
        """
        return self._call("use", [req_id]).tx_ids[-1]


    def _box(self, prefix: bytes, item_id: int) -> bytes:
        """
        Legge e decodifica il contenuto di un box numerato.

        Input:
            prefix: prefisso del box, b"l" per i laboratori o b"r" per le richieste
            item_id: ID del laboratorio o della richiesta
        Output:
            Contenuto del box.
        """
        if type(item_id) is not int or not 0 < item_id < 2**64:
            raise ValueError("Identificativo non valido")
        key = prefix + item_id.to_bytes(8, "big")

        try:
            value = self.algod.application_box_by_name(self.app_id, key)
        except AlgodHTTPError as exc:
            if exc.code == 404:
                resource = "Laboratorio" if prefix == b"l" else "Richiesta"
                raise LookupError(f"{resource} {item_id} inesistente.") from exc
            raise
        if not isinstance(value, dict):
            raise ValueError("Risposta del nodo non valida")
        return base64.b64decode(value["value"], validate=True)

    def _available(self, lab: Lab) -> None:
        """Verifica che il laboratorio ammetta le operazioni di accesso ordinarie."""
        if lab.registration != LAB_APPROVED:
            raise ValueError("Registrazione del laboratorio non approvata")
        if lab.status != LAB_ACTIVE:
            raise ValueError("Laboratorio inattivo")
        if lab.lock_id == 0:
            raise ValueError("Serratura non registrata")


    def _neighbors(self, req: Request) -> tuple[int, int]:
        """
        Trova la posizione nell'elenco ordinato per fine dell'intervallo.

        Input:
            req: richiesta da inserire nell'elenco
        Output:
            ID del precedente e del successivo nel formato tuple[int, int]
        """
        prev_id = 0
        next_id = self.lab(req.lab).head

        # set vuoto di interi per tracciare le richieste già visitate
        seen: set[int] = set()

        while next_id:
            if next_id in seen:
                raise ValueError("Elenco delle autorizzazioni non valido")
            
            seen.add(next_id)
            following = self.req(next_id)
            if (
                following.lab != req.lab
                or following.status not in (REQ_APPROVED, REQ_CONSUMED)
                or following.prev != prev_id
            ):
                raise ValueError("Errore elenco: elenco modificato")

            # Uscita dal ciclo nel caos di orario di fine maggiore o uguale a quello richiesto
            if following.end >= req.end:        
                break

            # Aggiornamento
            prev_id = next_id
            next_id = following.next
        return prev_id, next_id

    def _sender(self) -> str:
        """
        Verifica che sia configurato un mittente per le chiamate dell'account.

        Output:
            Indirizzo del mittente.
        """
        if self.sender is None:
            raise ValueError("Configurare il mittente prima di inviare una transazione")
        return self.sender


    def _payment(self, amount: int) -> TransactionWithSigner:
        """
        Prepara il pagamento da includere nel gruppo atomico.

        Input:
            amount: importo del pagamento in microAlgo
        Output:
            Transazione e firmatario.
        """
        sender = self._sender()
        signer = self.signer or self.algorand.account.get_signer(sender)

        # Preparazione della transazione
        txn = self.algorand.create_transaction.payment(
            PaymentParams(
                sender=sender,
                receiver=self.app.app_address,
                amount=AlgoAmount(micro_algo=amount),
                max_fee=AlgoAmount(micro_algo=MAX_FEE),
            )
        )
        return TransactionWithSigner(txn, signer)


    def _cost(self, name: str, args: list[Any]) -> int:
        """
        Legge un costo senza inviare una transazione alla blockchain.

        Input:
            name: nome del metodo che calcola il costo
            args: argomenti da passare al metodo
        Output:
            Costo in microAlgo.
        """
        result = self.app.send.call(
            AppClientMethodCallParams(method=name, args=args, sender=self._sender()),

            # Inserimento automatico delle risorse necessarie
            {"populate_app_call_resources": True, 
            # Disattivazione dei messaggi di log
             "suppress_log": True},    
        )
        if not isinstance(result.abi_return, int) or result.abi_return < 0:
            raise ValueError("Costo restituito dal contratto non valido")
        return result.abi_return


    def _call(self, name: str, args: list[Any]) -> SendAppTransactionResult[Any]:
        """
        Invia una chiamata ABI con le risorse necessarie e un limite alle commissioni.

        Input:
            name: nome del metodo da chiamare
            args: argomenti da passare al metodo
        Output:
            Risultato della chiamata nel formato SendAppTransactionResult[Any].
        """
        return self.app.send.call(
            AppClientMethodCallParams(
                method=name,
                args=args,
                sender=self._sender(),
                max_fee=AlgoAmount(micro_algo=MAX_FEE),
            ),
            {
                "populate_app_call_resources": True,
                "max_rounds_to_wait": 10,
                "suppress_log": True,
            },
        )
