import asyncio
import logging
import time

from eth_abi import abi
from eth_account import Account
from zksync2.core.types import PaymasterParams
from zksync2.signer.eth_signer import PrivateKeyEthSigner
from zksync2.transaction.transaction_builders import TxFunctionCall
from client import Client
from config import (
    SYNCSWAP_CONTRACTS, SYNCSWAP_POOL_FACTORY_ABI, TOKENS_PER_CHAIN, ZERO_ADDRESS,
    SYNCSWAP_POOL_ABI, SYNCSWAP_ROUTER_ABI, SYNCSWAP_PAYMASTER_ABI
)
from functions import get_choice_token

# Настройка логирования
file_log = logging.FileHandler('zksync2.log', encoding='utf-8')
console_out = logging.StreamHandler()
logging.basicConfig(handlers=(file_log, console_out),
                    level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")


class SyncSwap:
    def __init__(self, client: Client):
        self.client = client
        self.pool_factory_contract = self.client.get_contract(
            contract_address=SYNCSWAP_CONTRACTS[self.client.chain_name]['pool_factory'],
            abi=SYNCSWAP_POOL_FACTORY_ABI
        )
        self.router_contract = self.client.get_contract(
            contract_address=SYNCSWAP_CONTRACTS[self.client.chain_name]['router_v2'],
            abi=SYNCSWAP_ROUTER_ABI
        )

    async def get_min_amount_out(
            self, pool_address: str, from_token_address: str, amount_in_wei: int
    ):
        pool_contract = self.client.get_contract(contract_address=pool_address, abi=SYNCSWAP_POOL_ABI)
        min_amount_out = await pool_contract.functions.getAmountOut(
            from_token_address,
            amount_in_wei,
            self.client.address
        ).call()

        return min_amount_out

    async def swap(self, from_token_name: str, to_token_name: str, gas_token_name: str, amount_in_wei: int,
                   paymaster_mode: bool = False):
        tokens_config = TOKENS_PER_CHAIN[self.client.chain_name]

        from_token_address = tokens_config[from_token_name]
        to_token_address = tokens_config[to_token_name]

        pool_address = await self.pool_factory_contract.functions.getPool(
            from_token_address,
            to_token_address
        ).call()

        if pool_address == ZERO_ADDRESS:
            raise RuntimeError('This pool is not exist')

        min_amount_out_in_wei = await self.get_min_amount_out(pool_address, from_token_address, amount_in_wei)
        value = amount_in_wei if from_token_name == self.client.chain_token else 0
        deadline = int(time.time() + 1200)
        withdraw_mode = 1  # unwrap wETH

        swap_data = abi.encode(
            ["address", "address", "uint8"],
            [from_token_address, self.client.address, withdraw_mode]
        )

        steps = [
            pool_address,
            swap_data,
            ZERO_ADDRESS,
            '0x',
            True
        ]

        paths = [
            [steps],
            from_token_address if not from_token_name == self.client.chain_token else ZERO_ADDRESS,
            amount_in_wei,
        ]

        if from_token_name != self.client.chain_token:
            await self.client.make_approve(
                token_address=from_token_address, spender_address=self.router_contract.address,
                amount_in_wei=amount_in_wei
            )

        if not paymaster_mode:

            transaction = await self.router_contract.functions.swap(
                [paths],
                min_amount_out_in_wei,
                deadline
            ).build_transaction(await self.client.prepare_tx(value=value))
        else:

            transaction = await self.router_contract.functions.swap(
                [paths],
                min_amount_out_in_wei,
                deadline
            ).build_transaction(await self.client.prepare_tx(value=value))

            paymaster_contract = self.client.get_contract(
                contract_address=SYNCSWAP_CONTRACTS[self.client.chain_name]['paymaster'],
                abi=SYNCSWAP_PAYMASTER_ABI
            )

            paymaster_input_data = paymaster_contract.encode_abi(
                'approvalBased',
                args=(
                    TOKENS_PER_CHAIN['zkSync'][gas_token_name],
                    2000000000,
                    "0x000000000000000000000000000000000000000000000000000000000000000f"
                )
            )

            paymaster_params = PaymasterParams(**{
                "paymaster": paymaster_contract.address,
                "paymaster_input": self.client.w3.to_bytes(hexstr=paymaster_input_data)
            })

            tx_712 = TxFunctionCall(
                chain_id=transaction['chainId'],
                nonce=int(transaction['nonce']),
                from_=transaction['from'],
                to=transaction['to'],
                value=int(transaction['value']) if from_token_name == self.client.chain_token else 0,
                data=transaction['data'],
                gas_price=int(transaction['maxFeePerGas']),
                max_priority_fee_per_gas=int(transaction['maxPriorityFeePerGas']),
                paymaster_params=paymaster_params,
            ).tx712(int(transaction['gas']))

            account = Account.from_key(self.client.private_key)
            signer = PrivateKeyEthSigner(account, self.client.chain_id)

            signed_message = signer.sign_typed_data(tx_712.to_eip712_struct())

            msg = tx_712.encode(signed_message)
            return await self.client.send_transaction(ready_tx=msg)

        return await self.client.send_transaction(transaction, without_gas=True)


async def main():
    private_key = input("Введите private key: ")
    proxy = ''

    try:
        w3_client = Client(private_key=private_key, proxy=proxy)
    except Exception as er:
        logging.error(f"Произошла ошибка при иницализации клиента: {er}")
        exit(1)

    try:
        tokens_info = await w3_client.get_balance_tokens()
    except Exception as er:
        logging.error(f"Ошибка при получении баланса токенов {er}")

    print("-" * 30, "Выберите токен для свапа", "-" * 30)
    from_token = get_choice_token(tokens_info, input_amount=True, check_balance=True)
    amount_in_wei = from_token['amount_in_wei_user']

    print("-" * 30, "Выберите токен в который будем делать свап", "-" * 30)
    to_token = get_choice_token(tokens_info, input_amount=False, check_balance=False)

    print("-" * 30, "Выберите токен за счет которого будет браться газ", "-" * 30)
    gas_token = get_choice_token(tokens_info, input_amount=False, check_balance=True)

    zk2 = SyncSwap(client=w3_client)
    try:
        await zk2.swap(from_token['name'], to_token['name'], gas_token['name'], amount_in_wei, paymaster_mode=True)
    except Exception as er:
        logging.error(f"Произошла ошибка при свапе: {er}")

asyncio.run(main())
