from algokit_utils import AlgorandClient

def avvia_testnet():
    # Crea un client configuratoppypt per la TestNet
    chain = AlgorandClient.testnet()

    # Verifica che la rete sia TestNet
    if not chain.client.is_testnet():
        raise RuntimeError("Errore: la rete non è TestNet")

    print("Connessione alla TestNet verificata!")
    return chain


if __name__ == "__main__":
    avvia_testnet()
