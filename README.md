# Wallet API

DeFi wallet on Chia Network.

## Install


```
git clone https://github.com/Kiwihealthcare-Network/openapi/

# change config.py

# Run this shell first
sh install.sh

# Execute '. ./activate' before install packages.
. ./activate

# Install public packages
pip install -r requirements.txt

# Install blockchain packages
pip install -r requirements_kiwi.txt
or 
pip install -r requirements_chia.txt

# Run app
uvicorn kiwi_wallet_api:app
or 
uvicorn chia_wallet_api:app
```

## Thanks

Thanks to the contributions of [Chia Mine](https://github.com/Chia-Mine/clvm-js), MetaMask, Goby, and DeBank to crypto, we stand on your shoulders to complete this project. (🌱, 🌱)

Also, thanks to Catcoin and [Taildatabase](https://www.taildatabase.com/) for sharing the token list.

