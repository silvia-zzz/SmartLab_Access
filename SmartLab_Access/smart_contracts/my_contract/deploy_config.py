import os
from pathlib import Path

from algokit_utils import (
    AlgoAmount,
    AlgorandClient,
    AppClient,
    AppClientMethodCallParams,
    AppClientParams,
    AppFactory,
    AppFactoryCreateMethodCallParams,
    AppFactoryParams,
    PaymentParams,
)


def deploy() -> None:
    """
    Crea l'applicazione compilata e finanzia il saldo minimo iniziale 100.000 microALGO.
    """
    # Configurazione dell'ambiente
    path = Path(__file__).resolve().parents[1] / "artifacts" / "my_contract" / "Access.arc56.json"
    if not path.is_file():
        raise FileNotFoundError("Compila prima il contratto con python -m smart_contracts build")

    # risorsa: https://dev.algorand.co/docs/algokit-utils/python/latest/api/algokit_utils/algorand/
    chain = AlgorandClient.from_environment()

    # risorsa: https://dev.algorand.co/docs/algokit-utils/python/latest/api/algokit_utils/accounts/account_manager/
    admin = chain.account.from_environment("SYS_ADMIN")

    # Creazione dell'applicazione 
    # risorsa: https://dev.algorand.co/docs/algokit-utils/python/latest/concepts/building/app-client/#appfactory
    factory = AppFactory(
        AppFactoryParams(
            algorand=chain,
            app_spec=path.read_text(encoding="utf-8"),
            default_sender=admin.address,
        )
    )

    # risorsa: https://dev.algorand.co/docs/algokit-utils/python/latest/concepts/building/app-client/#appfactory
    app, result = factory.send.create(AppFactoryCreateMethodCallParams(method="create"))
    
    print(f"APP_ID={app.app_id}")
    print(f"Amministratore del sistema: {admin.address}")
    print(f"Transazione di creazione: {result.tx_id}")

    chain.send.payment(
        PaymentParams(
            sender=admin.address,
            receiver=app.app_address,

            # Saldo minimo tratto da:
            # https://dev.algorand.co/concepts/accounts/create/
            amount=AlgoAmount(micro_algo=100000),
        )
    )


def update() -> None:
    """Aggiorna il codice dell'applicazione esistente indicata da APP_ID."""
    path = Path(__file__).resolve().parents[1] / "artifacts" / "my_contract" / "Access.arc56.json"
    if not path.is_file():
        raise FileNotFoundError("Compila prima il contratto con python -m smart_contracts build")

    try:
        app_id = int(os.environ.get("APP_ID", "").strip())
    except ValueError as exc:
        raise ValueError("APP_ID mancante o non valido") from exc
    if not 0 < app_id < 2**64:
        raise ValueError("APP_ID fuori intervallo")

    chain = AlgorandClient.from_environment()
    admin = chain.account.from_environment("SYS_ADMIN")
    app = AppClient(
        AppClientParams(
            algorand=chain,
            app_spec=path.read_text(encoding="utf-8"),
            app_id=app_id,
            default_sender=admin.address,
            default_signer=admin.signer,
        )
    )

    # La versione gia distribuita deve autorizzare questa chiamata.
    # Un rifiuto interrompe l'operazione senza creare una nuova applicazione.
    result = app.send.update(AppClientMethodCallParams(method="update"))
    print(f"Contratto aggiornato: APP_ID={app.app_id}")
    print(f"Transazione di aggiornamento: {result.tx_id}")
