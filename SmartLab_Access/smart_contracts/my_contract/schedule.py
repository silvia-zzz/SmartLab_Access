from algopy import Global, UInt64, arc4, subroutine

from smart_contracts.my_contract.storage import Storage
from smart_contracts.my_contract.types import Request
from status_constants import REQ_APPROVED, REQ_CONSUMED


class Schedule(Storage):
    """
    Gestisce l'elenco delle prenotazioni dei laboratori, consentendo 
    l'inserimento e rimozione delle richieste.
    """
    
    @subroutine
    def _insert(self, req: Request, prev_id: UInt64, next_id: UInt64) -> Request:
        """
            Inserisce una richiesta nell'elenco del laboratorio.

            Input:
                req:        richiesta da inserire
                prev_id:    ID della prenotazione precedente
                next_id:    ID della prenotazione successiva
            Output:
                Richiesta inserita
        """
        lab = self._lab(req.lab.as_uint64())
        assert req.id != prev_id and req.id != next_id, "Vicino non valido"

        if prev_id:
            prev = self._req(prev_id)
            assert prev.lab == req.lab, "Laboratorio del vicino errato"

            assert prev.status == REQ_APPROVED or \
                    prev.status == REQ_CONSUMED, \
                        "Vicino non prenotato"
            
            assert prev.next == next_id, \
                "Vicini non consecutivi"
            assert prev.end <= req.start or prev.end <= Global.latest_timestamp, \
                "Intervalli sovrapposti"

            prev.next = req.id

            # Aggiornamento della lista
            self.reqs[prev_id] = prev.copy()

        else:
            # Inserimento in testa all'elenco
            assert lab.head == next_id, "Inizio elenco non valido"
            lab.head = req.id
            self.labs[req.lab.as_uint64()] = lab.copy()

        if next_id:
            # Caso non fosse l'ultimo della lista
            following = self._req(next_id)
            assert following.lab == req.lab, "Laboratorio del vicino errato"

            assert following.status == REQ_APPROVED or \
                    following.status == REQ_CONSUMED, \
                        "Vicino non prenotato"
            
            assert following.prev == prev_id, "Vicini non consecutivi"
            assert req.end <= following.start, "Intervalli sovrapposti"

            #Aggiornamento della lista
            following.prev = req.id
            self.reqs[next_id] = following.copy()

        req.prev = arc4.UInt64(prev_id)
        req.next = arc4.UInt64(next_id)
        return req.copy()

    @subroutine
    def _remove(self, req: Request) -> Request:
        """
        Rimuove una prenotazione dall'elenco del laboratorio e aggiorna i collegamenti.

        Input:
            req: prenotazione attualmente presente nell'elenco
        Output:
            Copia della richiesta con prev e next azzerati; conserva il box della 
            richiesta.
        """
        lab = self._lab(req.lab.as_uint64())

        if req.prev:            
            
            # Richiesta in mezzo all'elenco 
            prev_req = self._req(req.prev.as_uint64()) 

            assert prev_req.lab == req.lab and \
                prev_req.next == req.id, \
                "Collegamento non valido"
            
            prev_req.next = req.next
            self.reqs[prev_req.id.as_uint64()] = prev_req.copy()

        else:
            # Richiesta in testa all'elenco
            assert lab.head == req.id, "Inizio elenco non valido"
            lab.head = req.next
            self.labs[req.lab.as_uint64()] = lab.copy()

        if req.next:
            following = self._req(req.next.as_uint64())
            assert following.lab == req.lab \
                and following.prev == req.id, \
                "Collegamento non valido"
            
            following.prev = req.prev
            self.reqs[following.id.as_uint64()] = following.copy()
        
        req.prev = arc4.UInt64(0)
        req.next = arc4.UInt64(0)
        return req.copy()
