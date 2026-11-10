from algopy import arc4

class Lab(arc4.Struct):
    """Laboratorio gestito dallo smart contract"""

    id: arc4.UInt64         # ID del laboratorio
    admin: arc4.Address     # Indirizzo dell'amministratore
    lock_id: arc4.UInt64    # ID della serratura, oppure 0 se non associata
    status: arc4.UInt8      # Stato del laboratorio
    head: arc4.UInt64       # Prima prenotazione del laboratorio
    registration: arc4.UInt8  # Esito della verifica della registrazione


class Request(arc4.Struct):
    """Richiesta gestito dallo smart contract"""

    id: arc4.UInt64         # ID della richiesta
    user: arc4.Address      # Indirizzo dell'utente
    lab: arc4.UInt64        # ID del laboratorio
    start: arc4.UInt64      # Timestamp di inizio
    end: arc4.UInt64        # Timestamp di fine
    created: arc4.UInt64    # Orario di creazione
    status: arc4.UInt8      # Stato della richiesta
    prev: arc4.UInt64       # ID della richiesta precedente
    next: arc4.UInt64       # ID della richiesta successiva
