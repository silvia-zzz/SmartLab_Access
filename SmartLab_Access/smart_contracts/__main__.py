import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def build() -> None:
    """
        Compila il contratto Access con puyapy e aggiorna gli artefatti generati.

        Scrive gli artefatti del contratto, inclusi
        interfaccia ABI e bytecode, nella cartella artifacts/my_contract.

        Note:
            Nessun parametro esplicito; usa il file my_contract/contract.py
            e l'interprete Python corrente.
    """
    env = os.environ.copy()
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "puyapy",
            str(ROOT / "my_contract" / "contract.py"),
            "--out-dir",
            str(ROOT / "artifacts" / "my_contract"),
            "--output-bytecode",
        ],
        cwd=ROOT.parent,
        env=env,
        check=True,
    )


def main() -> None:
    """
        Carica la configurazione e avvia compilazione, deployment o aggiornamento.
        Esegue l'azione selezionata.

        Note:
            Legge l'azione build, deploy, all o update dalla riga
            di comando e la configurazione dal file .env. L'azione predefinita è build.
    """
    parser = argparse.ArgumentParser(description="Contratto di accesso ai laboratori")
    parser.add_argument("action", choices=("build", "deploy", "all", "update"), default="build", nargs="?")
    args = parser.parse_args()
    load_dotenv(ROOT.parent / ".env")
    # Anche update compila prima di inviare il nuovo codice.
    if args.action in ("build", "all", "update"):
        build()
    if args.action in ("deploy", "all"):
        from smart_contracts.my_contract.deploy_config import deploy

        deploy()

    elif args.action == "update":
        from smart_contracts.my_contract.deploy_config import update

        update()


if __name__ == "__main__":
    main()
