import os
import json
from typing import List, Optional, Dict
import logzero
import uvicorn
from logzero import logger
from fastapi import FastAPI, APIRouter, Request, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from aiocache import caches, cached
from pydantic import BaseModel
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash as inner_decode_puzzle_hash
from chia.types.spend_bundle import SpendBundle
from chia.types.blockchain_format.program import Program
import config as settings

caches.set_config(settings.CACHE_CONFIG)


app = FastAPI()

cwd = os.path.dirname(__file__)

log_dir = os.path.join(cwd, "logs")

if not os.path.exists(log_dir):
    os.mkdir(log_dir)

logzero.logfile(os.path.join(log_dir, "kiwi_wallet_api.log"), maxBytes=1e6, backupCount=3)


async def get_full_node_client() -> FullNodeRpcClient:
    config = settings.CHIA_CONFIG
    full_node_client = await FullNodeRpcClient.create(config['self_hostname'], config['full_node']['rpc_port'], settings.CHIA_ROOT_PATH, settings.CHIA_CONFIG)
    return full_node_client


@app.on_event("startup")
async def startup():
    app.state.client = await get_full_node_client()
    # check full node connect
    await app.state.client.get_blockchain_state()


@app.on_event("shutdown")
async def shutdown():
    app.state.client.close()
    await app.state.client.await_closed()


def to_hex(data: bytes):
    return data.hex()


def decode_puzzle_hash(address):
    try:
        return inner_decode_puzzle_hash(address)
    except ValueError:
        raise HTTPException(400, "Invalid Address")

def coin_to_json(coin):
    return {
        'parent_coin_info':  to_hex(coin.parent_coin_info),
        'puzzle_hash': to_hex(coin.puzzle_hash),
        'amount': str(coin.amount)
    }


router = APIRouter()


class UTXO(BaseModel):
    parent_coin_info: str
    puzzle_hash: str
    amount: str


@router.get("/utxos", response_model=List[UTXO])
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"utxos:{kwargs['address']}", alias='default')
async def get_utxos(address: str, request: Request):
    # todo: use blocke indexer and supoort unconfirmed param
    logger.info("/utxos request: %r", address)

    pzh = decode_puzzle_hash(address)
    full_node_client = request.app.state.client
    coin_records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=pzh, include_spent_coins=True)
    data = []

    for row in coin_records:
        if row.spent:
            continue
        data.append(coin_to_json(row.coin))

    logger.info("/utxos response: %r", data)
    return data


@router.post("/sendtx")
async def create_transaction(request: Request, item=Body({})):
    logger.info("/sendtx request: %r", item)

    spb = SpendBundle.from_json_dict(item['spend_bundle'])
    full_node_client = request.app.state.client

    try:
        resp = await full_node_client.push_tx(spb)
    except ValueError as e:
        logger.warning("sendtx: %s, error: %r", spb, e)
        raise HTTPException(400, str(e))

    data = {
        'status': resp['status'],
        'id': spb.name().hex()
    }
    logger.info("/sendtx response: %r", data)
    return data


@router.post("/sendtx_all")
async def create_transactions(request: Request, items=Body({})):
    logger.info("/sendtx_all request: %r", items)

    result = []
    for item in items:
        spb = SpendBundle.from_json_dict(item['spend_bundle'])
        full_node_client = request.app.state.client

        try:
            resp = await full_node_client.push_tx(spb)
            result.append({
                'status': resp['status'],
                'id': spb.name().hex(),
                'code': 200,
                'msg': '',
                'address': ''
            })
        except ValueError as e:
            logger.warning("sendtx_all: %s, error: %r", spb, e)
            result.append({
                'status': 'FAILED',
                'id': '',
                'code': 500,
                'msg': str(e),
                'address': ''
            })
    logger.info("/sendtx_all response: %r", result)
    return result


class ChiaRpcParams(BaseModel):
    method: str
    params: Optional[Dict] = None


@router.post('/chia_rpc')
async def full_node_rpc(request: Request, item: ChiaRpcParams):
    # todo: limit method and add cache
    logger.info("/chia_rpc request: %r", item)

    full_node_client = request.app.state.client
    async with full_node_client.session.post(full_node_client.url + item.method, json=item.params, ssl_context=full_node_client.ssl_context) as response:
        res_json = await response.json()

        logger.info("/chia_rpc response: %r", res_json)
        return res_json


async def get_user_balance(puzzle_hash: bytes, request: Request):
    full_node_client = request.app.state.client
    coin_records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash, include_spent_coins=True)
    amount = sum([c.coin.amount for c in coin_records if c.spent == 0])
    return amount


@router.get('/balance')
@cached(ttl=100, key_builder=lambda *args, **kwargs: f"balance:{kwargs['address']}", alias='default')
async def query_balance(address, request: Request):
    # todo: use blocke indexer and supoort unconfirmed param
    logger.info("/balance request: %r", address)
    puzzle_hash = decode_puzzle_hash(address)
    amount = await get_user_balance(puzzle_hash, request)
    data = {
        'amount': amount,
        'address': address
    }
    logger.info("/balance response: %r", data)
    return data


async def get_user_transactions(address: str, request: Request):
    logger.info("/transactions request: %r", address)

    try:
        if len(address) <= 0:
            return HTTPException(400, "Missing address")
        if not isinstance(address, str):
            return HTTPException(400, "Invalid address")

        puzzle_hash = decode_puzzle_hash(address)
        full_node_client = request.app.state.client

        coin_records_spent = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash, include_spent_coins=True)

        selected_network = settings.CHIA_CONFIG['selected_network']
        prefix = settings.CHIA_CONFIG['full_node']['network_overrides']['config'][selected_network]['address_prefix']

        # receieved coin info list
        received = {}
        send = []
        for record in coin_records_spent:
            if record.coin.amount == 0:
                continue

            parent_result = await full_node_client.get_coin_record_by_name(record.coin.parent_coin_info)
            if parent_result.coin.puzzle_hash != puzzle_hash:
                if record.coin.parent_coin_info not in received:
                    received[record.coin.parent_coin_info] = {
                        'type': 'receive',
                        'transactions': [],
                        'timestamp': record.timestamp,
                        'block': record.confirmed_block_index,
                        'amount': record.coin.amount,
                        'fee': record.coin.amount,
                        'puzzle_hash': str(record.coin.puzzle_hash),
                        'name': str(record.name)
                    }

                group_receive = received[record.coin.parent_coin_info]
                group_receive['transactions'].append({
                    'sender': encode_puzzle_hash(puzzle_hash=parent_result.coin.puzzle_hash, prefix=prefix),
                    'amount': record.coin.amount,
                })
                group_receive['fee'] -= record.coin.amount

            if record.spent:
                coin_id = record.name

                block_result_height = await full_node_client.get_block_record_by_height(record.spent_block_index)
                additions, removals = await full_node_client.get_additions_and_removals(block_result_height.header_hash)
                group_sender = {
                    'type': 'send',
                    'transactions': [],
                    'timestamp': block_result_height.timestamp,
                    'block': record.spent_block_index,
                    'amount': record.coin.amount,
                    'fee': record.coin.amount,
                    'puzzle_hash': str(record.coin.puzzle_hash),
                    'name': str(record.name)
                }

                for child in additions:
                    if str(child.coin.parent_coin_info).__eq__(str(coin_id)):
                        if child.coin.puzzle_hash != puzzle_hash:
                            group_sender['transactions'].append({
                                'destination': encode_puzzle_hash(puzzle_hash=child.coin.puzzle_hash, prefix=prefix),
                                'amount': child.coin.amount,
                            })
                        group_sender['fee'] -= child.coin.amount

                send.append(group_sender)

        received_array = []
        for key in received:
            received_item = received[key]
            received_array.append(received_item)

        transaction_groups = {
            'address': address,
            'send': send,
            'receive': received_array
        }

        logger.info("/transactions response: %r", transaction_groups)
        return transaction_groups
    except Exception as e:
        logger.error("transactions error: %r", e)
        return HTTPException(400, "Could not fetch transactions")


@router.get('/transactions')
@cached(ttl=100, key_builder=lambda *args, **kwargs: f"transactions:{kwargs['address']}", alias='default')
async def query_transactions(address, request: Request):
    return await get_user_transactions(address, request)


DEFAULT_TOKEN_LIST = [
    {
        'chain': 'xch',
        'id': 'xch',
        'name': 'XCH',
        'symbol': 'XCH',
        'decimals': 12,
        'logo_url': 'https://static.goby.app/image/token/xch/XCH_32.png',
        'is_verified': True,
        'is_core': True,
    },
    {
        'chain': 'xch',
        'id': '8ebf855de6eb146db5602f0456d2f0cbe750d57f821b6f91a8592ee9f1d4cf31',
        'name': 'Marmot',
        'symbol': 'MRMT',
        'decimals': 3,
        'logo_url': 'https://static.goby.app/image/token/mrmt/MRMT_32.png',
        'is_verified': True,
        'is_core': True,
    },
    {
        'chain': 'xch',
        'id': '78ad32a8c9ea70f27d73e9306fc467bab2a6b15b30289791e37ab6e8612212b1',
        'name': 'Spacebucks',
        'symbol': 'SBX',
        'decimals': 3,
        'logo_url': 'https://static.goby.app/image/token/sbx/SBX_32.png',
        'is_verified': True,
        'is_core': True,
    },
]


@router.get('/tokens')
async def list_tokens():
    return DEFAULT_TOKEN_LIST


app.include_router(router, prefix="/kiwi/v2")


# def main():
#     return query_transactions("tkik1d09r9nmkvr5t0gu2xgxpj4w6t9zc2gdgae8ewywxs7ty6h5lm6aq8klfue", Request)
#
#
# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=8000)
