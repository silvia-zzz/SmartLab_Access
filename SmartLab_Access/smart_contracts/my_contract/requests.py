from algopy import Bytes, Global, Txn, UInt64, arc4, gtxn, size_of, subroutine

from smart_contracts.my_contract.labs import Labs
from smart_contracts.my_contract.types import Request
from status_constants import (
    REQ_APPROVED, REQ_CONSUMED, REQ_EXPIRED, REQ_PENDING, REQ_REJECTED, REQ_REVOKED,
)


class Requests(Labs):
    """
    Gestisce le richieste di accesso ai laboratori e il loro ciclo di vita,
    dalla creazione fino all'utilizzo o alla scadenza.
    """
    
    @arc4.abimethod
    def request(
        self, 
        lab_id:arc4.UInt64, start:arc4.UInt64, end:arc4.UInt64, pay:gtxn.PaymentTransaction,
    ) -> arc4.UInt64:
        """
        Crea una richiesta monouso pagando il deposito esatto.

        Input:
            lab_id: ID di un laboratorio attivo
            start: timestamp iniziale;
            end: timestamp finale;
            pay: transazione di pagamento del deposito 
        Output:
            ID della nuova richiesta.
        """
        self._guard()
        lab = self._lab(lab_id.as_uint64())

        self._available(lab)
        assert start >= Global.latest_timestamp, \
            "Inizio nel passato"
        assert end > start, "Intervallo non valido"
        assert (end.as_uint64() - start.as_uint64()) % 3600 == 0, \
            "Durata non espressa in ore intere"

        current_user = arc4.Address(Txn.sender)
        key = self._key(current_user, lab_id, start, end)
        prev_id = self.slots.get(key, default=UInt64(0))

        # Caso della richiesta dell'utente per lo stesso laboratorio e intervallo di tempo
        if prev_id:
            prev = self._req(prev_id)
            assert (prev.status != REQ_PENDING and prev.status != REQ_APPROVED), \
                "Richiesta duplicata"

        prev_min_balance = Global.current_application_address.min_balance
        self.seq += 1
        req_id = self.seq
        assert req_id not in self.reqs, "Identificativo gia assegnato"

        self.reqs[req_id] = Request(
            arc4.UInt64(req_id),
            current_user,
            lab_id,
            start,
            end,
            arc4.UInt64(Global.latest_timestamp),
            arc4.UInt8(REQ_PENDING),
            arc4.UInt64(0),
            arc4.UInt64(0),
        )
        self.slots[key] = req_id
        self._pay(pay, Global.current_application_address.min_balance - prev_min_balance)
        return arc4.UInt64(req_id)


    @arc4.abimethod(readonly=True)
    def req_cost(
        self, lab_id: arc4.UInt64, user: arc4.Address, start: arc4.UInt64, end: arc4.UInt64,
    ) -> arc4.UInt64:
        """
        Calcola il deposito dei box per l'intervallo richiesto: escluse le commissioni; include il box dell'indice solo se la combinazione di utente, laboratorio e intervallo non esiste.

        Input:
            lab_id: ID di un laboratorio attivo
            user: indirizzo dell'utente che presenta la richiesta
            start: timestamp iniziale
            end: timestamp finale
        Output:
            Deposito in microAlgo.
        """
        self._guard()
        assert lab_id.as_uint64() in self.labs, "Laboratorio inesistente"
        key = self._key(user, lab_id, start, end)
        cost = 2500 + 400 * (9 + size_of(Request))

        # Caso in cui si crea una nuova richiesta
        if key not in self.slots:
            cost += 2500 + 400 * (1 + key.length + size_of(UInt64))

        return arc4.UInt64(cost)


    @arc4.abimethod
    def approve(self, req_id: arc4.UInt64, prev_id: arc4.UInt64, next_id: arc4.UInt64) -> None:
        """
        Approva una richiesta prima dell'inizio. 
        L'operazione richiede l'amministratore del laboratorio.

        Input:
            req_id: ID di una richiesta
            prev_id: ID della prenotazione precedente;
            next_id: ID della prenotazione successiva;
        """
        req = self._req(req_id.as_uint64())
        lab = self._lab(req.lab.as_uint64())

        self._owner(lab)

        self._available(lab)
        assert req.status == REQ_PENDING, "Richiesta non in attesa"
        assert req.start > Global.latest_timestamp, \
            "Intervallo gia iniziato"

        req = self._insert(req, prev_id.as_uint64(), next_id.as_uint64())
        req.status = arc4.UInt8(REQ_APPROVED)
        self.reqs[req_id.as_uint64()] = req.copy()


    @arc4.abimethod
    def reject(self, req_id: arc4.UInt64) -> None:
        """
        Rifiuta una richiesta nello stato di PENDING. 
        L'operazione richiede l'amministratore del laboratorio.

        Input:
            req_id: ID di una richiesta
        """
        req = self._req(req_id.as_uint64())
        self._owner(self._lab(req.lab.as_uint64()))
        assert req.status == REQ_PENDING, "Richiesta non in attesa"
        req.status = arc4.UInt8(REQ_REJECTED)
        self.reqs[req_id.as_uint64()] = req.copy()


    @arc4.abimethod
    def revoke(self, req_id: arc4.UInt64) -> None:
        """
        Revoca una richiesta precedentemente approvata. 
        L'operazione richiede l'amministratore del laboratorio.

        Input:
            req_id: ID di una richiesta;
        """
        req = self._req(req_id.as_uint64())
        self._owner(self._lab(req.lab.as_uint64()))
        assert req.status == REQ_APPROVED, "Richiesta non approvata"
        
        req = self._remove(req)
        req.status = arc4.UInt8(REQ_REVOKED)
        self.reqs[req_id.as_uint64()] = req.copy()


    @arc4.abimethod
    def use(self, req_id: arc4.UInt64) -> None:
        """
        Consuma il permesso di una richiesta già autorizzata del mittente.

        Input:
            req_id: ID della richiesta
        """
        self._guard()
        req = self._req(req_id.as_uint64())
        lab = self._lab(req.lab.as_uint64())

        assert Txn.sender == req.user.native, \
            "Utente non autorizzato"
        self._available(lab)
        assert req.status == REQ_APPROVED, "Richiesta non approvata"
        assert req.start <= Global.latest_timestamp, \
            "Intervallo non iniziato"
        assert req.end > Global.latest_timestamp, \
            "Richiesta scaduta"

        req.status = arc4.UInt8(REQ_CONSUMED)
        self.reqs[req_id.as_uint64()] = req.copy()


    @arc4.abimethod
    def expire(self, req_id: arc4.UInt64) -> None:
        """
        Registra la scadenza di una richiesta del mittente giunta al termine.

        Input:
            req_id: ID della richiesta
        """
        self._guard()
        req = self._req(req_id.as_uint64())
        assert Txn.sender == req.user.native, \
            "Utente non autorizzato"
        assert req.end <= Global.latest_timestamp, \
            "Richiesta non scaduta"

        if req.status == REQ_APPROVED:
            req = self._remove(req)
        elif req.status != REQ_PENDING:
            return
        
        req.status = arc4.UInt8(REQ_EXPIRED)
        self.reqs[req_id.as_uint64()] = req.copy()


    @arc4.abimethod(readonly=True)
    def get_req(self, req_id: arc4.UInt64) -> Request:
        """
        Restituisce i dati della richiesta associata all'ID inserito.

        Input:
            req_id: ID di una richiesta esistente
        Output:
            Richiesta associata.
        """
        self._guard()
        return self._req(req_id.as_uint64())


    @subroutine
    def _key(
        self, user: arc4.Address, lab_id: arc4.UInt64, start: arc4.UInt64, end: arc4.UInt64,
    ) -> Bytes:
        """
        Costruisce la chiave univoca utilizzata per identificare eventuali richieste 
        duplicate, concatenando le rappresentazioni in byte: dell'utente, del laboratorio 
        e dei timestamp di inizio e fine.

        Input:
            user: indirizzo dell'utente
            lab_id: identificativo del laboratorio
            start: timestamp iniziale
            end: timestamp finale
        Output:
            Sequenza di Bytes ottenuta concatenando utente, laboratorio, inizio e fine.
        """
        return user.bytes + lab_id.bytes + start.bytes + end.bytes
