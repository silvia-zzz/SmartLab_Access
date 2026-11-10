import time
from pathlib import Path

from algosdk import encoding, transaction

from simulation.client import Client
from simulation.models import Lab, Request
from simulation.store import Store
from status_constants import LAB_ACTIVE, LAB_APPROVED, REQ_APPROVED, REQ_CONSUMED

class Lock:
    def __init__(
        self, 
        client: Client,         # client dell'applicazione Algorand
        lab_id: int,            # ID del laboratorio
        lock_id: int,           # ID univoco della serratura
        path: str | Path        # percorso dell'archivio SQLite
    ) -> None:

        if type(lab_id) is not int or not 0 <= lab_id < 2**64:
            raise ValueError("ID laboratorio non valido")
        if type(lock_id) is not int or not 0 < lock_id < 2**64:
            raise ValueError("ID serratura non valido: deve essere un intero positivo minore di 2^64")
        self.client = client
        self.lab_id = lab_id
        self.lock_id = lock_id
        self.store = Store(path, client.genesis, client.app_id, lab_id, lock_id)


    def _lab(self, *, require_active: bool = True) -> Lab:
        """
        Verifica registrazione, associazione alla serratura e, se richiesto, attività.
        """
        lab = self.client.lab(self.lab_id)
        if lab.id != self.lab_id or lab.lock_id != self.lock_id:
            raise ValueError("La serratura non corrisponde al laboratorio")
        if lab.registration != LAB_APPROVED:
            raise ValueError("Registrazione del laboratorio non approvata")
        if require_active and lab.status != LAB_ACTIVE:
            raise ValueError("Laboratorio inattivo")
        return lab


    def _req(self, req_id: int, status: int | tuple[int, ...]) -> Request:
        """
        Verifica laboratorio, stato e intervallo della richiesta.

        Input:
            req_id: ID della richiesta
            status: stato atteso della richiesta
        Output:
            Risultato della verifica
        """
        self._lab()
        req = self.client.req(req_id)

        statuses = (status,) if isinstance(status, int) else status
        if req.id != req_id or req.lab != self.lab_id or req.status not in statuses:
            raise ValueError("Richiesta non valida per questa operazione")

        block_time= self.client.now()
        computer_time = int(time.time())

        if not req.start <= max(block_time, computer_time) < req.end:
            raise ValueError("Richiesta fuori dall'intervallo autorizzato")
        
        return req


    def check(self, req_id: int, user: str) -> None:
        """
        Verifica che l'utente corrisponda a quello associato alla richiesta e 
        che la richiesta si trovi nello stato approvato

        Input:
            req_id: ID della richiesta
            user: indirizzo dell'utente
        """
        req = self._req(req_id, REQ_APPROVED)
        if req.user != user:
            raise ValueError("La richiesta appartiene a un altro utente")

    def _confirm_use(self, txid: str, req: Request) -> None:
        """
        Verifica che la transazione sia confermata e corrisponde all'operazione "use"
        sulla richiesta indicata.

        Input:
            txid: ID della transazione
            req: richiesta associata alla transazione
        """
        txn = self.client.confirm(txid)
        
        if not isinstance(txn, transaction.ApplicationCallTxn) or \
            txn.index != self.client.app_id:
            raise ValueError("Transazione diretta a un'altra applicazione")
        if txn.on_complete != transaction.OnComplete.NoOpOC:
            raise ValueError("La chiamata deve essere NoOp")
        if txn.rekey_to is not None and \
            txn.rekey_to != encoding.encode_address(bytes(32)):
            raise ValueError("Rekey non consentito")
        if txn.sender != req.user:
            raise ValueError("La transazione non appartiene al richiedente")
        
        args = txn.app_args
        if args is None or len(args) != 2:
            raise ValueError("Argomenti della chiamata non validi")
        if args[0] != self.client.selector("use"):
            raise ValueError("Metodo diverso da use")
        if args[1] != req.id.to_bytes(8, "big"):
            raise ValueError("Transazione associata a un'altra richiesta")

    def _session_sender(self) -> str:
        """
        Richiede l'account configurato con la sua capacità di firma nella simulazione.
        """
        sender = self.client.sender
        if sender is None or self.client.signer is None:
            raise ValueError("Selezionare un account configurato con il proprio firmatario")
        return sender

    def get_code(self, req_id: int) -> str:
        """
        Consuma la richiesta una volta e nel caso di recupero restituisce sempre lo stesso PIN.
        """
        sender = self._session_sender()
        req = self._req(req_id, (REQ_APPROVED, REQ_CONSUMED))

        if req.user != sender:
            raise ValueError("La richiesta appartiene a un altro utente")
        
        if req.status == REQ_APPROVED:
            txid = self.client.use(req_id)
            self._confirm_use(txid, req)
            req = self._req(req_id, REQ_CONSUMED)
            if req.user != sender:
                raise ValueError("La richiesta appartiene a un altro utente")
            
        return self.store.get_pin(
            req.id, req.start, req.end, max(self.client.now(), int(time.time()))
        )

    def admin_access(self) -> bool:
        """
        Verifica se è l'amministratore associato a richiedere l'accesso.
        """
        sender = self._session_sender()
        lab = self._lab(require_active=False)
        if lab.admin != sender:
            raise ValueError("L'account corrente non amministra questo laboratorio")
        return True

    def open(self, req_id: int, pin: str) -> bool:
        """
        Simula l'apertura verificando la validitàà del codice.

        Input:
            req_id: ID della richiesta
            pin: codice inserito dall'utente
        Output:
            True concede l'accesso;
            False impedisce l'accesso.
        """
        req = self._req(req_id, REQ_CONSUMED)
        ticket = self.store.read_ticket(req_id)
        if (req.start, req.end) != (ticket.start, ticket.end):
            raise ValueError("Richiesta diversa dal codice memorizzato")
        return self.store.use(req_id, pin, max(self.client.now(), int(time.time())));
            

    def close(self) -> None:
        """
        Chiude l'archivio della serratura.
        """
        self.store.close()
