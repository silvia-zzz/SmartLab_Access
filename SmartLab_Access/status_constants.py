"""Stati condivisi tra smart contract e simulazione.

I valori numerici fanno parte dei dati salvati sulla blockchain.
"""

# Disponibilita del laboratorio
LAB_INACTIVE = 0
LAB_ACTIVE = 1

# Esito della registrazione del laboratorio
LAB_PENDING = 0
LAB_APPROVED = 1
LAB_REJECTED = 2

# Stati della richiesta
REQ_PENDING = 0
REQ_APPROVED = 1
REQ_REJECTED = 2
REQ_REVOKED = 3
REQ_EXPIRED = 4
REQ_CONSUMED = 5
