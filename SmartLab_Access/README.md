# Installazione e avvio su Algorand TestNet

Questa guida descrive come configurare ed eseguire il progetto su **Windows**, utilizzando **PowerShell**, **Python 3.13**, **Poetry 2** e la rete **Algorand TestNet**.

Si assume che **Python 3.13 sia già installato** e disponibile tramite il comando `python`.

La procedura prevede i seguenti passaggi:

1. preparazione di Poetry;
2. creazione dell'ambiente virtuale e installazione delle dipendenze;
3. creazione e configurazione del file `.env`;
4. generazione e finanziamento degli account TestNet;
5. verifica della connessione alla rete;
6. compilazione e deployment dello smart contract;
7. configurazione di `APP_ID`;
8. avvio del programma.

## 1. Preparazione di Poetry

Per installare **Poetry 2**, seguire la documentazione ufficiale:

https://python-poetry.org/docs/#installation

Aprire PowerShell e verificare che entrambi siano disponibili:

```powershell
python --version
poetry --version
```

Entrare quindi nella cartella principale del progetto, cioè quella che contiene `pyproject.toml`:

```powershell
cd "C:\percorso\del\progetto\SmartLab_Access"
```

## 2. Creazione dell'ambiente virtuale

Eseguire una sola volta i seguenti comandi:

```powershell
poetry env use python
poetry install --with dev
.\.venv\Scripts\python.exe -m pip install tzdata
```

Il primo comando indica a Poetry di utilizzare Python 3.13, già disponibile tramite `python`.

Il secondo crea l'ambiente virtuale `.venv` e installa le dipendenze definite in `pyproject.toml` e `poetry.lock`, comprese quelle necessarie per la compilazione dello smart contract.

`tzdata` viene installato separatamente perché è necessario per la gestione dei fusi orari su Windows e non è attualmente dichiarato in `pyproject.toml`.

Tutti i comandi successivi devono essere eseguiti dalla cartella principale del progetto.

Non è necessario attivare manualmente `.venv`, perché i comandi utilizzeranno direttamente il relativo interprete Python.

## 3. Creazione del file `.env`

Il file `.env.example` contiene la configurazione di base del progetto.

Il blocco seguente:

- crea il file `.env`;
- configura l'accesso ad Algorand TestNet;
- genera tre nuovi account di prova;
- lascia temporaneamente vuoto `APP_ID`, che verrà inserito dopo il deployment.

Il nodo pubblico utilizzato è quello fornito da Nodely e non richiede un token API.

Copiare l'intero blocco seguente in PowerShell:

```powershell
@'
from pathlib import Path
from algosdk import account, mnemonic
from dotenv import dotenv_values

path = Path(".env")

if path.exists():
    raise SystemExit(".env esiste gia: configurazione non modificata.")

config = dict(dotenv_values(".env.example"))

config.update({
    "ALGOD_SERVER": "https://testnet-api.4160.nodely.dev",
    "ALGOD_PORT": "443",
    "ALGOD_TOKEN": "",
    "APP_ID": "",
    "LAB_ID": "1",
})

for name in ("SYS_ADMIN", "LAB_ADMIN", "USER"):
    private_key, address = account.generate_account()
    config[f"{name}_MNEMONIC"] = mnemonic.from_private_key(private_key)
    print(f"{name}: {address}")

with path.open("x", encoding="utf-8") as file:
    file.write(
        "\n".join(
            f"{key}={value or ''}"
            for key, value in config.items()
        ) + "\n"
    )

print(".env creato. APP_ID verra inserito dopo il deployment.")
'@ | .\.venv\Scripts\python.exe -
```

Al termine vengono mostrati gli indirizzi di:

```text
SYS_ADMIN
LAB_ADMIN
USER
```

Conservare questi indirizzi, perché dovranno essere finanziati su TestNet.

Il file `.env` contiene anche le frasi mnemonic utilizzate per firmare le transazioni e non deve essere condiviso.

Se `.env` esiste già, lo script termina senza modificarlo.

## 4. Finanziamento degli account TestNet

I tre account:

```text
SYS_ADMIN
LAB_ADMIN
USER
```

devono possedere ALGO di TestNet per poter pagare le commissioni delle transazioni e il saldo minimo richiesto dalle risorse create dall'applicazione.

È possibile ottenere ALGO di prova tramite il dispenser TestNet:

https://lora.algokit.io/testnet/fund

Finanziare separatamente i tre indirizzi stampati durante la creazione del file `.env`.

La serratura non richiede un account Algorand. Il suo ID numerico positivo viene scelto durante l'associazione dal menu e deve essere univoco nell'applicazione; il valore 0 è riservato all'assenza di una serratura. La precedente variabile `LOCK_ADDRESS` non viene più utilizzata.

## 5. Verifica della connessione a TestNet

Prima di compilare e distribuire lo smart contract, verificare che la configurazione punti effettivamente ad Algorand TestNet.

Eseguire:

```powershell
.\.venv\Scripts\python.exe -c "from dotenv import load_dotenv; from algokit_utils import AlgorandClient; load_dotenv('.env'); chain = AlgorandClient.from_environment(); assert chain.client.is_testnet(), 'La configurazione non punta a TestNet'; print('TestNet confermata')"
```

Se la configurazione è corretta verrà mostrato:

```text
TestNet confermata
```

Procedere solo dopo che questo controllo ha avuto esito positivo e i tre account hanno ricevuto i fondi TestNet.

## 6. Compilazione dello smart contract

Compilare il contratto con:

```powershell
.\.venv\Scripts\python.exe -m smart_contracts build
```

Il comando genera gli artefatti necessari nella directory:

```text
smart_contracts/artifacts/my_contract
```

Tra questi è presente anche la specifica ARC-56 utilizzata dal client, ad esempio:

```text
Access.arc56.json
```

## 7. Deployment su TestNet

Creare una nuova applicazione sulla rete TestNet con:

```powershell
.\.venv\Scripts\python.exe -m smart_contracts deploy
```

Attendere il completamento del comando.

Al termine verranno mostrati alcuni dati, tra cui:

```text
APP_ID
indirizzo dell'amministratore del sistema
transaction ID della creazione
```

Il valore importante per l'esecuzione successiva è `APP_ID`.

## 8. Configurazione di `APP_ID`

Aprire il file `.env` con un editor di testo e individuare:

```text
APP_ID=
```

Inserire l'identificativo ottenuto durante il deployment.

Per esempio:

```dotenv
APP_ID=123456
```

Salvare il file.

Il comando di deployment non modifica automaticamente `.env`, quindi questo passaggio deve essere eseguito manualmente.

Se esiste già un'applicazione compatibile distribuita su TestNet, non è necessario effettuare un nuovo deployment: è sufficiente inserire il relativo `APP_ID`.

La versione con `lock_id` numerico modifica il formato dei laboratori e la firma ABI di `register_lock`. Richiede quindi un nuovo deployment rispetto alla versione con indirizzi della serratura e l'aggiornamento di `APP_ID`. I laboratori devono essere registrati nella nuova applicazione; i dati del vecchio contratto e i suoi archivi locali restano separati e non vengono convertiti automaticamente.

### Aggiornamento del contratto esistente

Le azioni disponibili per `python -m smart_contracts` sono:

| Azione | Operazione |
| --- | --- |
| `build` | Compila e genera gli artefatti, senza distribuire sulla rete. È l'azione predefinita. |
| `deploy` | Crea una nuova applicazione dagli artefatti già compilati, con un nuovo `APP_ID`. |
| `all` | Compila e poi crea una nuova applicazione. |
| `update` | Compila e poi aggiorna l'applicazione indicata da `APP_ID`. |

Per aggiornare una versione che supporta già questa operazione:

```powershell
.\.venv\Scripts\python.exe -m smart_contracts update
```

L'aggiornamento è autorizzato soltanto dall'amministratore del sistema, usando
l'account `SYS_ADMIN`, e mantiene lo stesso `APP_ID`. Se la compilazione fallisce
o la rete rifiuta l'aggiornamento, il comando si interrompe senza creare una nuova applicazione.

La precedente versione del contratto non autorizza gli aggiornamenti: per passare
alla versione aggiornabile occorre eseguire una volta `all` e configurare il nuovo
`APP_ID`. I dati della vecchia applicazione non vengono trasferiti automaticamente.
Per gli aggiornamenti successivi, conservare il metodo `update` nel contratto e
mantenere compatibili i dati on-chain e locali. I file SQLite e le relative chiavi
`.key` restano utilizzabili con lo stesso contesto di rete, applicazione, laboratorio
e serratura; eventuali cambiamenti di formato richiedono una migrazione esplicita.

## 9. Avvio del programma

Avviare il programma con:

```powershell
.\.venv\Scripts\python.exe -m simulation
```

All'avvio viene richiesto di scegliere uno degli account configurati nel file `.env`.

Per esempio:

```text
LAB_ADMIN
```

Il programma carica automaticamente l'indirizzo e il firmatario associati all'account selezionato.

I nomi `SYS_ADMIN`, `LAB_ADMIN` e `USER` sono semplici etichette utilizzate nell'ambiente di test. I permessi effettivi dipendono dagli indirizzi e dalle associazioni registrate nello smart contract.
