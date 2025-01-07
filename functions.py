import logging
# Настройка логирования
file_log = logging.FileHandler('functions.log', encoding='utf-8')
console_out = logging.StreamHandler()
logging.basicConfig(handlers=(file_log, console_out),
                    level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")




def get_choice_token(tokens_info: dict, input_amount=True, check_balance=True) -> dict:

    for i, key in enumerate(tokens_info.items(), 1):
        print(f"{i}. {key[0]} {key[1]['amount_in_wei'] / 10 ** key[1]['decimals']:.6f}")

    while True:
        try:
            choice_name = int(input("Выберите токен: "))
        except:
            logging.warning("Неверный символ еще раз!")
            continue
        if 1 <= choice_name <= len(tokens_info):

            selected_key = list(tokens_info.keys())[choice_name - 1]
            print(f"Вы выбрали: {selected_key}")
            token_info = tokens_info[selected_key]
            if check_balance:
                if token_info['amount_in_wei'] == 0:
                    logging.error("Нулевой баланс, выходим!")
                    exit(1)
            if input_amount:
                while True:
                    try:
                        amount = float(input("Введите количество токена: "))
                        amount_in_wei_user = int(amount * 10 ** token_info['decimals'])
                        if amount_in_wei_user > token_info['amount_in_wei']:
                            logging.warning('Введённое количество превышает баланс')
                            continue
                    except:
                        logging.warning("Неверный символ еще раз!")
                        continue
                    token_info.update({'amount_in_wei_user': amount_in_wei_user})
                    break
            return tokens_info[selected_key]
        else:
            logging.warning("Неверный выбор. Попробуйте снова.")


