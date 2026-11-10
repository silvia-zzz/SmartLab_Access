from dataclasses import dataclass

from status_constants import LAB_APPROVED


@dataclass(frozen=True)
class Lab:
    """Laboratorio per simulazione sul computer"""

    id: int         # Identificativo del laboratorio
    admin: str      # Indirizzo dell'amministratore
    lock_id: int    # ID della serratura, oppure 0 se non associata
    status: int     # Stato del laboratorio
    head: int       # ID della prima prenotazione, oppure 0 se assente
    registration: int = LAB_APPROVED  # Esito della domanda di registrazione


@dataclass(frozen=True)
class Request:
    """Richieste per simulazione sul computer"""

    id: int         # Identificativo della richiesta    
    user: str       # Indirizzo dell'utente
    lab: int        # Identificativo del laboratorio
    start: int      # Timestamp iniziale
    end: int        # Timestamp finale
    created: int    # Timestamp di creazione
    status: int     # Stato della richiesta
    prev: int       # ID della prenotazione precedente, oppure 0 se assente
    next: int       # ID della prenotazione successiva, oppure 0 se assente
