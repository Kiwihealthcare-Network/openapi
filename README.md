# openapi

DeFi wallet on Chia Network.

## Install

You can install Goby [here](https://chrome.google.com/webstore/detail/goby/jnkelfanjkeadonecabehalmbgpfodjm).

## Run your own node

```
git clone https://github.com/GobyWallet/openapi.git
# change config.py

# public package
pip install -r requirements.txt

# blockchain package(can only install one blockchain package in the system)
pip install -r requirements_kiwi.txt

uvicorn kiwi_wallet_api:app
```

## Thanks

Thanks to the contributions of [Chia Mine](https://github.com/Chia-Mine/clvm-js), MetaMask, and DeBank to crypto, we stand on your shoulders to complete this project. (🌱, 🌱)

Also, thanks to Catcoin and [Taildatabase](https://www.taildatabase.com/) for sharing the token list.

