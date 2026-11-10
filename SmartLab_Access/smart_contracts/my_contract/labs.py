from algopy import Global, Txn, UInt64, arc4, gtxn, size_of

from smart_contracts.my_contract.schedule import Schedule
from smart_contracts.my_contract.types import Lab
from status_constants import LAB_ACTIVE, LAB_INACTIVE, LAB_APPROVED, LAB_PENDING, LAB_REJECTED


class Labs(Schedule):
    """
    Gestisce i laboratori e le relative serrature, consentendo la registrazione,
    la modifica dello stato e la consultazione dei dati dei laboratori.
    """    

    @arc4.abimethod
    def register_lab(
            self, 
            lab_id: arc4.UInt64, pay: gtxn.PaymentTransaction
        ) -> None:
        """
        Presenta una domanda di registrazione. Il mittente paga il deposito del
        laboratorio e ne sara l'amministratore dopo l'approvazione del sistema.

        Input:
            lab_id: ID del nuovo laboratorio
            pay:    pagamento del deposito nello stesso gruppo della chiamata
        """
        self._guard()
        
        assert lab_id.as_uint64() not in self.labs,\
            "Laboratorio gia registrato"

        prev_min_balance = Global.current_application_address.min_balance

        self.labs[lab_id.as_uint64()] = Lab(
            lab_id, arc4.Address(Txn.sender), arc4.UInt64(0),
            arc4.UInt8(LAB_INACTIVE), arc4.UInt64(0), arc4.UInt8(LAB_PENDING),
        )

        # Controlla i dati del pagamento
        self._pay(pay, Global.current_application_address.min_balance - prev_min_balance)

    @arc4.abimethod(readonly=True)
    def lab_cost(self) -> arc4.UInt64:
        """
        Calcola il deposito necessario per registrare un laboratorio.

        Output:
            Deposito in microAlgo del box del laboratorio, escluse le commissioni.
        """
        self._guard()
        return arc4.UInt64(2500 + 400 * (9 + size_of(Lab)))

    @arc4.abimethod
    def review_lab(self, lab_id: arc4.UInt64, approved: arc4.Bool) -> None:
        """
        Registra la decisione del sistema su una domanda ancora in attesa.
        """
        self._guard()
        assert Txn.sender == self.admin, "Revisore non autorizzato"

        lab = self._lab(lab_id.as_uint64())
        assert lab.registration == LAB_PENDING, \
            "Registrazione gia valutata"
        assert Txn.sender != lab.admin.native, \
            "Autovalutazione non consentita"
        
        if approved.native:
            lab.registration = arc4.UInt8(LAB_APPROVED)
        else:
            lab.registration = arc4.UInt8(LAB_REJECTED)
        self.labs[lab_id.as_uint64()] = lab.copy()

    @arc4.abimethod
    def register_lock(
        self, lab_id: arc4.UInt64, lock_id: arc4.UInt64, pay: gtxn.PaymentTransaction,
    ) -> None:
        """
        Associa un ID di serratura positivo e univoco a un laboratorio approvato.
        """
        lab = self._lab(lab_id.as_uint64())
        self._owner(lab)
        assert lab.lock_id == 0, \
            "Laboratorio con serratura gia registrata"
        assert lock_id > 0, \
            "ID serratura non valido"
        assert lock_id.as_uint64() not in self.locks, \
            "ID serratura gia assegnato"

        prev_min_balance = Global.current_application_address.min_balance
        lab.lock_id = lock_id
        self.labs[lab_id.as_uint64()] = lab.copy()
        self.locks[lock_id.as_uint64()] = lab_id.as_uint64()
        self._pay(
            pay, 
            Global.current_application_address.min_balance - prev_min_balance
            )

    @arc4.abimethod(readonly=True)
    def lock_cost(self) -> arc4.UInt64:
        """
        Deposito in microAlgo per il box che associa una serratura al laboratorio.
        """
        self._guard()
        return arc4.UInt64(2500 + 400 * (9 + size_of(UInt64)))

    @arc4.abimethod
    def set_active(self, lab_id: arc4.UInt64, active: arc4.Bool) -> None:
        """
        Attiva o disattiva il laboratorio amministrato.

        Input:
            lab_id: ID del laboratorio
            active: True per attivarlo, False per disattivarlo
        """
        lab = self._lab(lab_id.as_uint64())
        self._owner(lab)
        if active.native:
            assert lab.lock_id != 0, \
                "Serratura non registrata"
            lab.status = arc4.UInt8(LAB_ACTIVE)
        else:
            lab.status = arc4.UInt8(LAB_INACTIVE)
        self.labs[lab_id.as_uint64()] = lab.copy()

    @arc4.abimethod(readonly=True)
    def get_lab(self, lab_id: arc4.UInt64) -> Lab:
        """
        Restituisce i dati di un laboratorio.

        Input:
            lab_id: ID di un laboratorio registrato
        Output:
            Laboratorio associato all'ID inserito.
        """
        self._guard()
        return self._lab(lab_id.as_uint64())
