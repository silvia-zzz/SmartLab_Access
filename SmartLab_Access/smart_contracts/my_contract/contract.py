from algopy import Txn, arc4

from smart_contracts.my_contract.requests import Requests


class Access(Requests):
    """
    Gestisce la creazione dell'applicazione, l'assegnazione iniziale
    dell'amministratore e l'autorizzazione degli aggiornamenti.
    """
    
    @arc4.abimethod(create="require")
    def create(self) -> None:
        """
        Assegna al creatore il ruolo di amministratore del sistema.
        Il metodo è disponibile solo durante la creazione dell'applicazione.
        """
        self._guard()
        self.admin = Txn.sender

    @arc4.abimethod(create="disallow", allow_actions=["UpdateApplication"])
    def update(self) -> None:
        """Consente solo all'amministratore di aggiornare il contratto."""
        self._guard()
        assert Txn.sender == self.admin, "Amministratore non autorizzato"
