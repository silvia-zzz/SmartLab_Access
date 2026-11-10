import os
import re
import sys
import subprocess

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from algokit_utils import AlgorandClient
from algosdk import account, error, mnemonic
from dotenv import load_dotenv

from simulation.client import Client
from simulation.lock import Lock

from simulation.models import Lab
from status_constants import (
    LAB_ACTIVE, 
    LAB_APPROVED, LAB_PENDING, LAB_REJECTED,
    REQ_PENDING, REQ_APPROVED, REQ_CONSUMED, REQ_EXPIRED, REQ_REJECTED, REQ_REVOKED, 
)

ROOT = Path(__file__).resolve().parents[1]

REQUEST_STATES = {
    REQ_PENDING: "PENDING", 
    REQ_APPROVED: "APPROVED", 
    REQ_REJECTED: "REJECTED",
    REQ_REVOKED: "REVOKED", 
    REQ_EXPIRED: "EXPIRED", 
    REQ_CONSUMED: "CONSUMED",
}
REGISTRATION_STATES = {
    LAB_PENDING: "In attesa", 
    LAB_APPROVED: "Approvata", 
    LAB_REJECTED: "Rifiutata",
}


@dataclass(frozen=True)
class Session:
    """
    Rappresenta la sessione dell'utente corrente.
    """
    account: str
    client: Client
    reviewer: bool


class OperationCancelled(Exception):
    """Interrompe l'inserimento dei dati e restituisce il controllo al menu."""


def clear_screen() -> None:
    """
    Pulisce il terminale interattivo senza alterare l'output reindirizzato.
    """
    if not sys.stdout.isatty():
        return
    if os.name == "nt":
        subprocess.run("cls", shell=True, check=False)
    else:
        print("\033[2J\033[H", end="", flush=True)


def start_screen(title: str) -> None:
    """
    Inizia una schermata con il suo titolo.
    """
    clear_screen()
    print(f"{title}\n")


def pause() -> None:
    """
    Lascia visibile il risultato finché l'utente non preme Invio.
    """
    try:
        input("\nPremi Invio per continuare...")
    except KeyboardInterrupt:
        print()


def ask(
    label: str, convert: Callable[[str], Any] = str, default: Any = None,
    *, show_cancel_hint: bool = True,
) -> Any:
    """
    Richiede e valida un valore.

    Input:
        label: testo mostrato all'utente per indicare il dato da inserire.
        convert: funzione utilizzata per convertire o validare il valore inserito.
                 Se non specificata, il valore rimane una stringa.
        default: valore predefinito utilizzato se l'utente preme Invio
                 senza inserire alcun valore.
        show_cancel_hint: mostra l'avviso su Ctrl+C prima dell'inserimento.

    Restituisce:
        Il valore inserito dall'utente dopo la conversione/validazione.
    """
    if show_cancel_hint:
        print("Ctrl+C per annullare e tornare indietro.")
    while True:
        hint = f" [{default}]" if default is not None and default != "" else ""
        try:
            value = input(f"{label}{hint}: ").strip()
        except KeyboardInterrupt:
            print()
            raise OperationCancelled from None

        if value.casefold() == "/annulla":
            raise OperationCancelled

        if not value and default is not None:
            value = str(default)

        if not value:
            print("Inserisci un valore.")
            continue
        
        try:
            return convert(value)
        
        except ValueError as exc:
            print(f"Valore non valido: {exc}")


def validate_int(value: str, minimum: int = 1) -> int:
    """
    Valida e converte la stringa in input in un numero intero.

    Input:
        value: valore da verificare
        minimum: valore minimo consentito
    Output:
        Numero intero validato
    """
    if not value.isascii() or not value.isdecimal():
        raise ValueError("Inserisci un numero intero.")
    
    number = int(value)
    if not minimum <= number < 2**64:
        raise ValueError(f"Inserisci un numero intero maggiore o uguale a {minimum}.")
    return number


def validate_date(value: str) -> datetime:
    """Converte una data valida nel formato giorno/mese/anno."""
    try:
        return datetime.strptime(value, "%d/%m/%Y")
    except ValueError:
        raise ValueError("Inserisci una data valida nel formato GG/MM/YYYY.") from None


def validate_hour(value: str) -> int:
    """Accetta un'ora intera compresa tra 0 e 23."""
    hour = validate_int(value, 0)
    if hour > 23:
        raise ValueError("L'ora di inizio deve essere compresa tra 0 e 23.")
    return hour


def lab_id() -> int:
    """
    Richiede all'utente di inserire l'ID di un laboratorio.
    """
    return ask("Inserimento dell'ID laboratorio", validate_int)


def request_id() -> int:
    """
    Richiede all'utente di inserire l'ID di una richiesta.
    """
    return ask("Inserimento dell'ID richiesta", validate_int)


def lock_id() -> int:
    """Richiede un ID positivo per identificare la serratura nell'applicazione."""
    return ask("Inserimento dell'ID serratura", validate_int)



def menu(menu_str: str, options: dict[int, str]) -> int:
    """
    Mostra le opzioni; la voce 0 permette di annullare, tornare indietro o uscire.

    Input:
        menu_str: stringa per la stampa del menu
        options: opzioni disponibili nel menu
    Output:
        Numero intero dell'opzione selezionata dall'utente
    """
    start_screen(menu_str)
    for key, label in options.items():
        print(f"{key}. {label}")
    while True:
        try:
            choice = ask("Inserisci l'opzione (numero)", lambda value: validate_int(value, 0))
        except OperationCancelled:
            return 0
        if choice in options:
            return choice
        print("Scegli una delle opzioni indicate dal menu.")


def choose_session() -> Session:
    """
    Seleziona esplicitamente un account configurato per la simulazione.

    Output:
        Sessione dell'utente selezionato.
    """
    try:
        app_id = validate_int(os.getenv("APP_ID", "").strip())
    except ValueError as exc:
        raise ValueError(
            "APP_ID mancante o non valido: configura nel file .env l'ID dell'applicazione distribuita."
        ) from exc

    # recupero dati da un file .env configurato
    names = sorted(
        key.removesuffix("_MNEMONIC") for key, value in os.environ.items()
        if key.endswith("_MNEMONIC") and value.strip()
    )

    if not names:
        raise ValueError("Nessun account configurato con suffisso *_MNEMONIC nel file .env.")
    print("Account configurati: " + ", ".join(names))

    name = ask(
        "Inserimento dell'account",
        lambda value: configured_account(value, names),
    )

    # creazione client Algorand
    chain = AlgorandClient.from_environment()
    actor = chain.account.from_environment(name)
    client = Client(chain, app_id, sender=actor.address, signer=actor.signer)

    return Session(name, client, actor.address == client.system_admin())

def configured_account(value: str, names: list[str]) -> str:
    """
    Verifica che l'account inserito sia valido e configurato.

    Input:
        value: nome dell'account da verificare
        names: nomi degli account configurati
    Output:
        Nome dell'account validato
    """      
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value) or value not in names:
        raise ValueError("Scegli uno degli account configurati elencati sopra.")
    return value


def account_names() -> dict[str, str]:
    """
    Associa gli indirizzi ai nomi configurati, senza accessi alla rete.
    """
    names = {}
    for key, value in sorted(os.environ.items()):
        if not key.endswith("_MNEMONIC") or not value.strip():
            continue
        try:
            private_key = mnemonic.to_private_key(value.strip())
            account_address = account.address_from_private_key(private_key)
        except (ValueError, error.WrongMnemonicLengthError, error.WrongChecksumError):
            continue
        names.setdefault(account_address, key.removesuffix("_MNEMONIC"))
    return names


def show_labs(labs: Iterable[Lab]) -> None:
    """
    Mostra le informazioni dei laboratori disponibili.

    Input:
        labs: lista dilaboratori da visualizzare
    """
    names = account_names()
    found = False
    for lab in labs:
        found = True
        registration = REGISTRATION_STATES.get(lab.registration, "Sconosciuta")
        availability = "Attivo" if lab.status == LAB_ACTIVE else "Disattivato"
        lock = "Da associare" if lab.lock_id == 0 else f"ID {lab.lock_id}"

        admin = f"{names[lab.admin]} ({lab.admin})" if lab.admin in names else lab.admin
        print(f"Laboratorio {lab.id} | Registrazione: {registration} | Stato: {availability}")
        print(f"Amministratore: {admin}")
        print(f"Serratura: {lock}")
        head = f"Richiesta {lab.head}" if lab.head else "Nessuna"
        print(f"Prima prenotazione nell'elenco: {head}\n")
        
    if not found:
        print("Nessun laboratorio trovato.")


def list_labs(client: Client, *, own: bool = False) -> None:
    """Mostra i laboratori disponibili, oppure tutti quelli del proprio account."""
    labs = client.labs(own=own)
    if not own:
        labs = (
            lab for lab in labs
            if lab.registration == LAB_APPROVED
            and lab.status == LAB_ACTIVE
            and lab.lock_id != 0
        )
    show_labs(labs)


def create_request(client: Client) -> None:
    """
    Raccoglie i dati necessari per una richiesta di accesso a un laboratorio.
    """
    selected_lab = lab_id()
    lab = client.lab(selected_lab)
    if lab.admin == client.sender:
        print("Sei l'amministratore di questo laboratorio: non serve presentare una richiesta.")
        return
    client._available(lab)

    date = ask("Inserisci la data nel formato GG/MM/YYYY", validate_date, show_cancel_hint=False)
    start_hour = ask("Inserisci l'ora di inizio", validate_hour, show_cancel_hint=False)
    start_datetime = date.replace(
        hour=start_hour, minute=0, second=0, tzinfo=ZoneInfo("Europe/Rome")
    )
    while True:
        hours = ask("Numero di ore di utilizzo", validate_int, show_cancel_hint=False)
        try:
            end_datetime = start_datetime + timedelta(hours=hours)
            break
        except OverflowError:
            print("Valore non valido: il numero di ore supera l'intervallo di date supportato.")
    start = int(start_datetime.timestamp())
    end = int(end_datetime.timestamp())

    print(" \nRiepilogo della richiesta\n"\
            f"Lab ID richiesto: {selected_lab}\n"\
            f"Data di inizio: {start_datetime.strftime('%d/%m/%Y %H:%M')}\n"\
            f"Data di fine: {end_datetime.strftime('%d/%m/%Y %H:%M')}\n"\
            f"Ore di utilizzo: {hours}"
        )

    req_id, txid = client.request(selected_lab, start, end)
    print(
        f"\nRichiesta presentata: {req_id}\n"\
        f"Transazione: {txid}"
        )


def show_requests(client: Client, *, lab_id: int | None = None) -> bool:
    """Mostra le richieste visibili, con filtro facoltativo per laboratorio; indica se ne trova."""
    found = False
    timezone = ZoneInfo("Europe/Rome")
    for req in client.visible_requests():
        if lab_id is not None and req.lab != lab_id:
            continue
        found = True
        status = REQUEST_STATES.get(req.status, "Sconosciuto")
        start = datetime.fromtimestamp(req.start, timezone).strftime("%d/%m/%Y %H:%M")
        end = datetime.fromtimestamp(req.end, timezone).strftime("%d/%m/%Y %H:%M")
        created = datetime.fromtimestamp(req.created, timezone).strftime("%d/%m/%Y %H:%M:%S")
        print(f"Richiesta {req.id} | Laboratorio {req.lab} | Stato: {status}")
        print(f"Richiedente: {req.user}")
        print(f"Inizio: {start} | Fine: {end}")
        print(f"Presentata il: {created} (orari Europe/Rome)\n")
    if not found:
        if lab_id is None:
            print("Nessuna richiesta trovata per te o per i laboratori che amministri.")
        else:
            print(f"Nessuna richiesta trovata per il laboratorio {lab_id}.")
    return found


def access_code(client: Client) -> None:
    """
    Gestisce l'accesso a un laboratorio tramite PIN o accesso amministratore.
    """
    selected_lab = lab_id()
    lab = client.lab(selected_lab)

    if lab.registration != LAB_APPROVED:
        raise ValueError("Registrazione del laboratorio non approvata.")
    if lab.lock_id == 0:
        raise ValueError("Il laboratorio non ha ancora una serratura associata.")

    req = None if lab.admin == client.sender else client.access_request(selected_lab)
    path = ROOT / ".local" / f"lock-{client.app_id}-{selected_lab}.sqlite"
    lock = Lock(client, selected_lab, lab.lock_id, path)

    try:
        if req is None:
            lock.admin_access()
            print("Accesso amministratore consentito: serratura aperta.")
        else:
            pin = lock.get_code(req.id)
            print(f"Codice di accesso: {pin}")

    finally:
        lock.close()


def choose_request_status(current_status: int | None = None) -> int | None:
    """
    Restituisce lo stato scelto per la richiesta, oppure None per annullare.
    """
    title = "Inserimento dello stato finale"
    if current_status is not None:
        title += f"\nStato attuale: {REQUEST_STATES.get(current_status, 'Sconosciuto')}"
    choice = menu(
        title, {
        1: "APPROVED (approvare)",
        2: "REJECTED (rifiutare)",
        3: "REVOKED (revocare)",
        0: "Annullare",
    })
    return {
        1: REQ_APPROVED,
        2: REQ_REJECTED,
        3: REQ_REVOKED,
        0: None,
    }[choice]


def choose_lab_availability() -> bool | None:
    """Restituisce True per attivare, False per disattivare, None per annullare."""
    choice = menu(
        "Disponibilita del laboratorio", {
            1: "Attivare",
            2: "Disattivare",
            0: "Annullare",
        }
    )
    if choice == 0:
        return None
    return choice == 1


def handle_lab_menu(client: Client) -> None:
    """
    Mostra i laboratori dell'account e gestisce quello selezionato.
    """
    owned_labs = list(client.labs(own=True))
    print("I tuoi laboratori:\n")
    show_labs(owned_labs)
    if not any(lab.registration == LAB_APPROVED for lab in owned_labs):
        print("Non amministri alcun laboratorio approvato. La gestione non e disponibile.")
        pause()
        return
    selected_lab = lab_id()
    while True:
        lab = client.authorized_lab(selected_lab)
        choice = menu(
            f"Gestione del laboratorio {selected_lab}", {
            1: "Modificare lo stato di una richiesta",
            2: "Attivare o disattivare il laboratorio",
            3: "Visualizzare i dati del laboratorio",
            0: "Tornare al menu principale",
        })
        try:
            if choice == 0:
                return
            
            if choice == 1:
                start_screen(f"Modificare lo stato di una richiesta | Laboratorio {selected_lab}")
                if not show_requests(client, lab_id=selected_lab):
                    pause()
                    continue
                req_id = request_id()
                req = client.req(req_id)

                if req.lab != selected_lab:
                    raise ValueError("La richiesta appartiene a un altro laboratorio.")
                new_status = choose_request_status(req.status)
                if new_status is None:
                    continue

                txid = client.change_request_status(selected_lab, req_id, new_status)
                print(f"Stato aggiornato. Transazione: {txid}")

            elif choice == 2:
                active = choose_lab_availability()
                if active is None:
                    continue

                txid = client.set_active(selected_lab, active)
                print(f"Disponibilita aggiornata. Transazione: {txid}")
            
            else:
                start_screen("Dati del laboratorio")
                show_labs([lab])
            
        except OperationCancelled:
            print("Operazione annullata.")
        except Exception as exc:
            print(f"{exc}")
        pause()


def handle_registrations_menu(client: Client) -> None:
    """
    Gestisce la registrazione di un laboratorio e della relativa serratura.
    """
    while True:
        choice = menu(
            "Registrazione", {
            1: "Registrare un laboratorio",
            2: "Registrare la serratura",
            0: "Tornare al menu principale",
        })
        try:
            if choice == 0:
                return
            
            start_screen(
                "Registrazione del laboratorio" \
                if choice == 1 else "Registrazione della serratura"
            )
            selected_lab = lab_id()
            if choice == 1:
                txid = client.register_lab(selected_lab)
                print(f"Domanda registrata, in attesa di verifica.\nTransazione: {txid}")
            
            else:
                client.authorized_lab(selected_lab)
                selected_lock = lock_id()
                txid = client.register_lock(selected_lab, selected_lock)

                print(f"Serratura registrata. Transazione: {txid}")
                print("Il laboratorio puo essere attivato dal menu di gestione.")

        except OperationCancelled:
            print("Operazione annullata.")
        except Exception as exc:
            print(f"{exc}")
        pause()


def handle_lab_registration(client: Client) -> None:
    """
    Gestisce l'approvazione della registrazione dei laboratori.
    """
    if client.sender != client.system_admin():
        raise ValueError("Verifica riservata all'account di sistema.")
    
    pending = list(client.pending_labs())
    show_labs(pending)
    if not pending:
        return
    selected_lab = lab_id()
    lab = client.lab(selected_lab)
    if lab.registration != LAB_PENDING:
        raise ValueError("Questo laboratorio non ha una registrazione in attesa di valutazione.")
    decision = menu(
        f"Decisione sulla registrazione del laboratorio {selected_lab}", {
        1: "Approvare", 
        2: "Rifiutare", 
        0: "Annullare",
    })
    if decision == 0:
        print("Verifica della registrazione annullata.")
        return
    else:
        txid = client.review_lab(selected_lab, decision == 1)
        print(f"Decisione registrata. Transazione: {txid}")


def main_menu(session: Session) -> bool:
    """
    Gestisce il menu principale della sessione utente.

    Input:
        session: sessione dell'utente corrente
    Output:
        True se l'utente richiede di cambiare account, False se richiede di terminare
    """
    client = session.client
    while True:
        options = {
            1: "Presentare una richiesta",
            2: "Visualizzare i laboratori disponibili",
            3: "Visualizzare richieste",
            4: "Ottenere il codice di accesso",
            5: "Registrazione laboratorio o serratura",
            6: "Gestire un laboratorio",
            7: "Cambiare account",
        }
        if session.reviewer:
            options[8] = "Gestire le registrazioni dei laboratori"

        options[0] = "Uscire"
        choice = menu(
            f"Benvenuto, {session.account}\n\n"
            "================================ Menu principale ================================", 
            options)
        try:
            if choice == 0:
                return False
            if choice == 7:
                return True

            start_screen(options[choice])
            if choice == 1:
                create_request(client)
            elif choice == 2:
                list_labs(client)
            elif choice == 3:
                show_requests(client)
            elif choice == 4:
                access_code(client)
            elif choice == 5:
                handle_registrations_menu(client)
                continue
            elif choice == 6:
                handle_lab_menu(client)
                continue
            elif choice == 8:
                handle_lab_registration(client)

        except OperationCancelled:
            print("Operazione annullata.")
        except Exception as exc:
            print(f"Operazione non completata: {exc}")
        pause()


def interactive() -> None:
    """
    Gestisce la sessione interattiva del programma.
    """
    while True:
        start_screen(
            "=======================================================\n" \
            "       Benvenuto nella simulazione degli accessi       \n" \
            "=======================================================")
        print(
            "Scegli un account gia configurato.\n"\
            "Digita il nome dell'account; Ctrl+C per uscire.\n")
        try:
            session = choose_session()
            if not main_menu(session):
                break
        except OperationCancelled:
            break
        except Exception as exc:
            print(f"Accesso non completato: {exc}")
            pause()
    print("Sessione terminata.")


def main() -> None:
    load_dotenv(ROOT / ".env")
    try:
        interactive()
    except (EOFError, KeyboardInterrupt):
        print("\nSessione terminata.")


if __name__ == "__main__":
    main()
