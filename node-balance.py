import subprocess
import csv
from datetime import datetime
import requests  # Biblioteca para requisições HTTP

# Configurações do Bot do Telegram
TELEGRAM_TOKEN = ""  # Substitua pelo token do seu bot
CHAT_ID = ""      # Substitua pelo ID do chat

NODE_NAME = ""
FULL_PATH_BOS = "/home/admin/balanceofsatoshis/"

TOTAL_OTHERS = 0
TOTAL_OTHER_FEES = 0
OTHER_FEES = ""

def execute_command(command):
    """Executa um comando no terminal e retorna a saída."""
    output = subprocess.check_output(command, shell=True, text=True)
    return output

def process_csv(csv_data, notes_filter=None):
    """Processa dados CSV e calcula totais com base em filtros."""
    global TOTAL_OTHER_FEES, OTHER_FEES
    total_amount = 0
    csv_reader = csv.DictReader(csv_data.splitlines())
    for row in csv_reader:
        if notes_filter is None or row['Notes'] == notes_filter:
            total_amount += float(row['Amount'])
        if row['Notes'] != "" and row['Notes'] != "Circular payment routing fee" and row['Type'] == "fee:network":
            OTHER_FEES += f"  Type:{row['Notes']} : {float(row['Amount']):.2f} SATS Transaction Type: {row['Type']}\n"
            TOTAL_OTHER_FEES += float(row['Amount'])
    return total_amount

def process_invoice_csv(csv_data):
    """Processa o CSV de invoices e retorna detalhes de transações."""
    global TOTAL_OTHERS
    csv_reader = csv.DictReader(csv_data.splitlines())
    for row in csv_reader:
        if row['Notes'] != "":
            TOTAL_OTHERS += float(row['Amount'])
            return f"  Type:{row['Notes']} : {float(row['Amount']):.2f} SATS Transaction Type: {row['Type']}\n"
    return ""

def process_onchain_csv(csv_data, transaction_type):
    """Processa o CSV de transações on-chain e retorna detalhes formatados."""
    csv_reader = csv.DictReader(csv_data.splitlines())
    result = ""
    for row in csv_reader:
        result += f"  Type:{row['Notes']} : {float(row['Amount']):.2f} SATS Transaction Type: {transaction_type}\n"
    return result

def send_telegram_message(message):
    """Envia uma mensagem para o Telegram usando a API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"  # Permite formatação com HTML
    }
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Erro ao enviar mensagem para o Telegram: {e}")

if __name__ == "__main__":
    # Obter data atual
    current_date = datetime.now()
    day = current_date.day
    month = current_date.month

    # Comandos BOS para coletar dados
    rebalance_command = f"{FULL_PATH_BOS}bos accounting 'payments' --date {day} --month {month} --disable-fiat --csv"
    forwards_command = f"{FULL_PATH_BOS}bos accounting 'forwards' --date {day} --month {month} --disable-fiat --csv"
    invoices_command = f"{FULL_PATH_BOS}bos accounting 'invoices' --date {day} --month {month} --disable-fiat --csv"
    chainfees_command = f"{FULL_PATH_BOS}bos accounting 'chain-fees' --date {day} --month {month} --disable-fiat --csv"
    chainsends_command = f"{FULL_PATH_BOS}bos accounting 'chain-sends' --date {day} --month {month} --disable-fiat --csv"
    chainreceives_command = f"{FULL_PATH_BOS}bos accounting 'chain-receives' --date {day} --month {month} --disable-fiat --csv"
    rebalance_lifetime_command= f"{FULL_PATH_BOS}bos accounting 'payments' --disable-fiat --csv"
    forwards_lifetime_command= f"{FULL_PATH_BOS}bos accounting 'forwards' --disable-fiat --csv"
    
    

    # Executar os comandos
    rebalance_output = execute_command(rebalance_command)
    forwards_output = execute_command(forwards_command)
    invoices_output = execute_command(invoices_command)
    chainfees_output = execute_command(chainfees_command)
    chainsends_output = execute_command(chainsends_command)
    chainreceives_output = execute_command(chainreceives_command)
    rebalance_lifetime_output = execute_command(rebalance_lifetime_command)
    forwards_lifetime_output = execute_command(forwards_lifetime_command)
      
  

    # Processar os dados
    total_rebalance_costs = float(process_csv(rebalance_output, notes_filter='Circular payment routing fee'))
    total_forwards_income = float(process_csv(forwards_output))
    lifetime_forwards = float(process_csv(forwards_lifetime_output))
    #lifetime_costs = process_csv(rebalance_lifetime_output, notes_filter='Circular payment routing fee')
    

    # Construir o relatório
    report = f"<b>⚡️ {NODE_NAME} - Daily Balance</b>\n"
    report += f"Forwards Income: {total_forwards_income:.2f} sats\n"
    report += f"Rebalance Costs: {total_rebalance_costs:.2f} sats\n"
    report += f"Daily Profit: {total_forwards_income + total_rebalance_costs:.2f} sats\n"

    report += "\n<b>Others Off-Chain Spend:</b>\n"
    report += OTHER_FEES
    report += f"Total: {TOTAL_OTHER_FEES:.2f} sats\n"

    report += "\n<b>Others Off-Chain Incomes:</b>\n"
    invoice_details = process_invoice_csv(invoices_output)
    report += invoice_details
    report += f"Total: {TOTAL_OTHERS:.2f} sats\n"
    report += f"Off-chain Operation Profit: {total_forwards_income + TOTAL_OTHERS + TOTAL_OTHER_FEES + total_rebalance_costs:.2f} sats\n"

    report += "\n<b>On-chain Balance</b>\n"
    report += "On-chain Fees:\n"
    report += process_onchain_csv(chainfees_output, "chain-fee")
    report += "On-chain Sends:\n"
    report += process_onchain_csv(chainsends_output, "chain-send")
    report += "On-chain Receives:\n"
    report += process_onchain_csv(chainreceives_output, "chain-receive")

    report += f"\nLifetime forwards: {lifetime_forwards:.2f} sats\n"
    report += f"Lifetime costs: {process_csv(rebalance_lifetime_output, notes_filter='Circular payment routing fee'):.2f} sats\n"
    report += f"Lifetime Profit: {lifetime_forwards + process_csv(rebalance_lifetime_output, notes_filter='Circular payment routing fee'):.2f} sats"

    # Enviar o relatório para o Telegram
    send_telegram_message(report)
