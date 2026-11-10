import json
import os
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from simulation.pin import hash_pin, verify_pin


@dataclass(frozen=True)
class Ticket:
    """
    Raggruppa i dati che la serratura conserva localmente 
    riguardo al codice di accesso associato a una richiesta.
    """
    
    req_id: int     # ID richiesta
    start: int      # Timestamp iniziale di validità
    end: int        # Timestamp finale di validità
    salt: bytes     # Valore casuale usato nel calcolo dell'hash
    digest: bytes   # Risultato dell'hash del codice di accesso
    used: bool      # Almeno un utilizzo riuscito; non impedisce altri accessi


class Store:
    """
    Gestisce l'archivio SQLite locale della serratura, consentendo la
    memorizzazione e la verifica dei codici associati alle richieste di accesso.
    Ogni codice viene generato una sola volta ed è riutilizzabile nel suo intervallo.
    L'hash verifica il codice; una copia cifrata permette di mostrarlo nuovamente.
    """

    def __init__(
        self, 
        path: str | Path,       # Percorso dell'archivio SQLite
        genesis: str,           # Hash genesis della rete Algorand
        app_id: int,            # ID dell'applicazione
        lab_id: int,            # ID del laboratorio
        lock_id: int            # ID univoco della serratura
    ) -> None:

        if type(lock_id) is not int or not 0 < lock_id < 2**64:
            raise ValueError("ID serratura non valido")
        # Percorso del database e apertura della connessione SQLite
        path = Path(path).expanduser().resolve()
        self.key_path = path.with_suffix(".key")
        self.context = (genesis, str(app_id), str(lab_id), str(lock_id))

        # Creazione della directory se non esiste
        path.parent.mkdir(parents=True, exist_ok=True)

        # Creazione della connessione al database SQLite
        self.db = sqlite3.connect(path, timeout=10)

        # Accedere ai valori con il nome della colonna
        self.db.row_factory = sqlite3.Row

        try:
            # Configurazione SQLite
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            with self._write():
                self.db.execute(
                    """CREATE TABLE IF NOT EXISTS config (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        genesis TEXT NOT NULL,
                        app_id TEXT NOT NULL,
                        lab_id TEXT NOT NULL,
                        lock_id TEXT NOT NULL
                    )"""
                )
                config = self.context
                columns = {column["name"] for column in self.db.execute("PRAGMA table_info(config)")}
                if "lock_id" not in columns:
                    raise ValueError("Archivio della precedente versione con indirizzi: usare un nuovo archivio per il contratto con ID serratura")
                row = self.db.execute(
                    "SELECT genesis, app_id, lab_id, lock_id FROM config WHERE id = 1"
                ).fetchone()

                if row is None:
                    self.db.execute("INSERT INTO config VALUES (1, ?, ?, ?, ?)", config)
                elif tuple(row) != config:
                    raise ValueError("Archivio associato a un'altra serratura o rete")
                
                self._schema()

        except Exception:
            self.db.close()
            raise



    def read_ticket(self, req_id: int) -> Ticket:
        """
        Recupera i dati del ticket per la richiesta inserita.

        Input:
            req_id: ID della richiesta
        Output:
            Dati del ticket.
        """
        row = self.db.execute(
                "SELECT * FROM tickets WHERE req_id = ?", (str(req_id),)
            ).fetchone()
        
        if row is None:
            raise ValueError("Nessun ticket trovato per richiesta inserita")
        
        return Ticket(
            req_id=int(row["req_id"]),
            start=int(row["start"]),
            end=int(row["end"]),
            salt=row["salt"],
            digest=row["digest"],
            used=bool(row["used"]),
        )


    def issue(self, req_id: int, start: int, end: int, pin: str) -> None:
        """
        Registra un solo rilascio salvando hash e copia cifrata del PIN.

        Input:
            req_id: ID della richiesta
            start: timestamp iniziale di validità
            end: timestamp finale di validità
            pin: codice di accesso
        """
        self._validate_pin(pin)

        with self._write():
            row = self.db.execute(
                "SELECT req_id FROM tickets WHERE req_id = ?", (str(req_id),)
            ).fetchone()

            if row is not None:
                raise ValueError("Codice gia rilasciato per questa richiesta")

            self._insert(req_id, start, end, pin)

    def get_pin(self, req_id: int, start: int, end: int, now: int) -> str:
        """
        Restituisce il PIN esistente o ne crea uno solo, anche con chiamate concorrenti.
        """
        self._validate_interval(start, end, now)
        with self._write():
            row = self.db.execute(
                "SELECT * FROM tickets WHERE req_id = ?", (str(req_id),)
            ).fetchone()
            if row is not None:
                return self._recover(row, start, end)
            pin = f"{secrets.randbelow(1_000_000):06d}"
            self._insert(req_id, start, end, pin)
            return pin

    def retrieve(self, req_id: int, start: int, end: int, now: int) -> str:
        """
        Recupera un PIN già emesso, controllandone intervallo e integrità.
        """
        self._validate_interval(start, end, now)
        with self._write():
            row = self.db.execute(
                "SELECT * FROM tickets WHERE req_id = ?", (str(req_id),)
            ).fetchone()
            if row is None:
                raise ValueError("Nessun ticket trovato per richiesta inserita")
            return self._recover(row, start, end)

    @staticmethod
    def _validate_pin(pin: str) -> None:
        if len(pin) != 6 or not pin.isascii() or not pin.isdecimal():
            raise ValueError("Codice non valido")

    @staticmethod
    def _validate_interval(start: int, end: int, now: int) -> None:
        if not start <= now < end:
            raise ValueError("Richiesta fuori dall'intervallo autorizzato")

    def _binding(self, req_id: int, start: int, end: int) -> dict[str, object]:
        return {
            "version": 1,
            "context": list(self.context),
            "req_id": str(req_id),
            "start": str(start),
            "end": str(end),
        }

    def _insert(self, req_id: int, start: int, end: int, pin: str) -> None:
        # Tutte le operazioni sulla chiave avvengono sotto il lock SQLite.
        cipher = self._cipher(create=True)
        payload = self._binding(req_id, start, end) | {"pin": pin}
        encrypted = cipher.encrypt(json.dumps(payload, sort_keys=True).encode("utf-8"))
        salt, digest = hash_pin(pin)
        self.db.execute(
            """INSERT INTO tickets (req_id, start, end, salt, digest, encrypted_pin)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(req_id), str(start), str(end), salt, digest, encrypted),
        )

    def _recover(self, row: sqlite3.Row, start: int, end: int) -> str:
        if (int(row["start"]), int(row["end"])) != (start, end):
            raise ValueError("Richiesta diversa dal codice memorizzato")
        token = row["encrypted_pin"]
        if token is None:
            raise ValueError(
                "PIN precedente salvato solo come hash: non recuperabile. "
                "Il codice originale resta utilizzabile; non viene generato un altro PIN."
            )
        cipher = self._cipher(create=False)
        try:
            payload = json.loads(cipher.decrypt(token))
        except (InvalidToken, ValueError, TypeError) as exc:
            raise ValueError("PIN cifrato non leggibile: chiave errata o archivio alterato") from exc
        if not isinstance(payload, dict):
            raise ValueError("Dati del PIN cifrato non validi")
        pin = payload.pop("pin", None)
        if payload != self._binding(int(row["req_id"]), start, end):
            raise ValueError("PIN cifrato associato a un'altra richiesta o serratura")
        if not isinstance(pin, str):
            raise ValueError("Dati del PIN cifrato non validi")
        self._validate_pin(pin)
        if not verify_pin(pin, row["salt"], row["digest"]):
            raise ValueError("Hash e copia cifrata del PIN non corrispondono")
        return pin

    def _cipher(self, *, create: bool) -> Fernet:
        existing = self.db.execute(
            "SELECT encrypted_pin FROM tickets WHERE encrypted_pin IS NOT NULL LIMIT 1"
        ).fetchone()
        try:
            key = self.key_path.read_bytes()
        except FileNotFoundError:
            if not create or existing is not None:
                raise ValueError(
                    "Chiave di cifratura mancante: ripristinare il file .key originale; "
                    "i PIN esistenti non vengono sostituiti"
                ) from None
            key = Fernet.generate_key()
            try:
                # O_EXCL impedisce di sostituire una chiave creata da altri processi.
                descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                key = self.key_path.read_bytes()
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(key)
                    handle.flush()
                    os.fsync(handle.fileno())
        try:
            cipher = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise ValueError("Chiave di cifratura non valida: ripristinare il file .key originale") from exc
        # Prima di cifrare nuovi PIN, accerta che la chiave apra quelli esistenti.
        if create and existing is not None:
            try:
                cipher.decrypt(existing["encrypted_pin"])
            except InvalidToken as exc:
                raise ValueError("Chiave errata o archivio alterato: nessun nuovo PIN creato") from exc
        return cipher

    def use(self, req_id: int, pin: str, now: int) -> bool:
        """
        Verifica il codice nell'intervallo e registra che è stato utilizzato.

        Input:
            req_id: ID della richiesta
            pin:    codice inserito dall'utente
            now:    timestamp corrente
        Output:
            Risultato della funzione
        """
        if len(pin) != 6 or not pin.isascii() or not pin.isdecimal():
            return False
        
        with self._write():
            ticket = self.read_ticket(req_id)

            # Verifica dell'intervallo
            if not ticket.start <= now < ticket.end:
                return False

            # Verifica del pin
            if not verify_pin(pin, ticket.salt, ticket.digest):
                return False
            
            self.db.execute(
                "UPDATE tickets SET used = 1 WHERE req_id = ?", (str(req_id),)
            )
            return True

    def close(self) -> None:
        """
        Chiude la connessione all'archivio locale.
        """
        self.db.close()


    def _schema(self) -> None:
        """
        Crea la tabella dei ticket nel formato corrente, se non esiste.
        """
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS tickets (
                req_id TEXT PRIMARY KEY NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                salt BLOB NOT NULL CHECK (length(salt) = 16),
                digest BLOB NOT NULL CHECK (length(digest) = 32),
                used INTEGER NOT NULL DEFAULT 0 CHECK (used IN (0, 1)),
                encrypted_pin BLOB
            )"""
        )
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(tickets)")}
        if "encrypted_pin" not in columns:
            # Migrazione additiva: i vecchi hash restano validi e non sono rigenerati.
            self.db.execute("ALTER TABLE tickets ADD COLUMN encrypted_pin BLOB")

    def _write(self) -> sqlite3.Connection:
        """
        Avvia una transazione e restituisce la connessione da usare.
        """
        self.db.execute("BEGIN IMMEDIATE")
        return self.db
