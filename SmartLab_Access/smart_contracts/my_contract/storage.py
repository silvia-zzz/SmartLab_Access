from algopy import ARC4Contract, Account, BoxMap, Bytes, Global, Txn, UInt64, gtxn, subroutine

from smart_contracts.my_contract.types import Lab, Request
from status_constants import LAB_ACTIVE, LAB_APPROVED


class Storage(ARC4Contract):
    """
    Definisce lo stato del contratto, le mappe utilizzate per memorizzare
    laboratori e richieste e le funzioni interne comuni per il controllo
    e il recupero dei dati.
    """
    
    def __init__(self) -> None:
        
        self.admin = Account()
        self.seq = UInt64(0)

        self.labs = BoxMap(UInt64, Lab, key_prefix=b"l")
        """Mappa: (UInt64) ID laboratorio -> (Lab) laboratorio associato"""

        self.reqs = BoxMap(UInt64, Request, key_prefix=b"r")
        """Mappa: (UInt64) ID richiesta -> (Request) richiesta associata"""

        self.locks = BoxMap(UInt64, UInt64, key_prefix=b"k")
        """Mappa: (UInt64) ID della serratura -> (UInt64) ID del laboratorio"""

        self.slots = BoxMap(Bytes, UInt64, key_prefix=b"o")
        """Mappa: (Bytes) (utente, lab_ID, inizio, fine) -> (UInt64) ID richiesta"""


    @subroutine
    def _guard(self) -> None:
        """
        Verifica che la transazione non utilizzi il rekeying.
        """
        assert Txn.rekey_to == Global.zero_address, "Rekey non consentito"

    @subroutine
    def _pay(self, pay: gtxn.PaymentTransaction, cost: UInt64) -> None:
        """
        Verifica la validità di un gruppo atomico composto da una transazione di pagamento seguita dalla chiamata all'applicazione.

        Input:
            pay:    transazione di pagamento da verificare
            cost:   importo esatto richiesto, espresso in microALGO
        """
        self._guard()
        
        assert Global.group_size == 2, "Gruppo non valido"
        assert Txn.group_index == 1, "Chiamata fuori posizione"
        assert pay.group_index == 0, "Pagamento fuori posizione"
        assert pay.sender == Txn.sender, \
            "Pagante diverso dal mittente"
        assert pay.receiver == Global.current_application_address, \
            "Destinatario errato"
        assert pay.amount == cost, "Importo non esatto"

        assert pay.rekey_to == Global.zero_address, "Rekey del pagamento non consentito"
        assert pay.close_remainder_to == Global.zero_address, "Chiusura non consentita"
        assert Global.current_application_address.balance >= Global.current_application_address.min_balance, "Saldo applicazione insufficiente"

    @subroutine
    def _lab(self, lab_id: UInt64) -> Lab:
        """
        La funzione recupera un laboratorio registrato, verificandone l'esistenza.

        Input:
            lab_id: identificativo del laboratorio
        Output:
            Lab associata all'identificativo.
        """
        assert lab_id in self.labs, "Laboratorio inesistente"
        return self.labs[lab_id].copy()

    @subroutine
    def _req(self, req_id: UInt64) -> Request:
        """
        La funzione recupera una richiesta registrata, verificandone l'esistenza.

        Input:
            req_id: identificativo della richiesta
        Output:
            Request associata all'identificativo.
        """
        assert req_id in self.reqs, "Richiesta inesistente"
        return self.reqs[req_id].copy()

    @subroutine
    def _owner(self, lab: Lab) -> None:
        """
        Verifica che il mittente sia l'amministratore del laboratorio.

        Input:
            lab: laboratorio di cui verificare l'amministratore
        """
        self._guard()
        assert lab.registration == LAB_APPROVED, \
            "Registrazione non approvata"
        assert Txn.sender == lab.admin.native, \
            "Amministratore non autorizzato"

    @subroutine
    def _available(self, lab: Lab) -> None:
        """
        Verifica che il laboratorio possa accettare accessi ordinari.
        """
        assert lab.registration == LAB_APPROVED, "Registrazione non approvata"
        assert lab.status == LAB_ACTIVE, "Laboratorio inattivo"
        assert lab.lock_id != 0, "Serratura non registrata"
