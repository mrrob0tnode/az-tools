import subprocess
import json
import logging
import os
import io
import qrcode
import pytz
from PIL import Image
from pyzbar.pyzbar import decode
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode
from functools import wraps

# Emojis para feedback visual
SUCCESS_EMOJI = "✅"
ERROR_EMOJI = "❌"
PAY_EMOJI = "💸"
MONEY_EMOJI = "💰"
ATTENTION_EMOJI = "⚠️"

# Usuários autorizados (substitua pelos IDs reais)
AUTHORIZED_USERS = []  # Lista de inteiros

# Configuração de logging
logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(message)s')

# Decorador para restringir acesso
def authorized_only(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.message.from_user.id
        if user_id not in AUTHORIZED_USERS:
            await update.message.reply_text(f"{ERROR_EMOJI} Você não está autorizado a usar este bot.")
            return
        log_action(update.message, func.__name__)
        return await func(update, context, *args, **kwargs)  # Usando await para chamar a função decorada
    return wrapper

# Função para registrar ações no log (síncrona)
def log_action(message, action):
    logging.info(f"Usuário {message.from_user.id} executou: {action}")

# Função para executar comandos lncli (síncrona)
def execute_lncli_addinvoice(amount, memo, expiry):
    cmd = f"lncli addinvoice --amt={amount} --memo='{memo}' --expiry={expiry}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    output = result.stdout.strip()
    if "r_hash" in output:
        data = json.loads(output)
        return data["r_hash"], data["payment_request"]
    return f"Erro ao criar invoice: {output}", None

# Função para gerar invoice com QR code (síncrona)
def generate_invoice_with_qr(amount, memo, expiry):
    r_hash, payment_request = execute_lncli_addinvoice(amount, memo, expiry)
    if "Erro" in r_hash:
        return r_hash, None, None
    
    # Criar QR code
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(payment_request)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Salvar em buffer
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    
    return r_hash, payment_request, buf

# Função para decodificar QR code de uma imagem (síncrona)
def decode_qr_from_image(image_path):
    img = Image.open(image_path)
    decoded_objects = decode(img)
    if decoded_objects:
        return decoded_objects[0].data.decode("utf-8")
    return None

# Função para enviar mensagens longas (assíncrona)
async def send_long_message(chat_id, text, context):
    if len(text) > 4096:
        for i in range(0, len(text), 4096):
            await context.bot.send_message(chat_id, text[i:i+4096], parse_mode=ParseMode.MARKDOWN)
    else:
        await context.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)

# Comando /start
@authorized_only
async def start_command(update, context):
    await update.message.reply_text(f"{SUCCESS_EMOJI} Bem-vindo ao Bot da Lightning Network! Use /help para ver os comandos disponíveis.")

# Comando /help
@authorized_only
async def help_command(update, context):
    help_text = (
        f"{SUCCESS_EMOJI} Comandos Disponíveis:\n"
        "/invoiceqr <valor> <memo> <expiração> - Gera uma invoice com QR code\n"
        "/sendonchain <endereço> <valor> <taxa> - Envia satoshis onchain\n"
        "/pay <payment_request> - Paga uma invoice via texto\n"
        "(Envie uma foto de QR code) - Paga uma invoice via QR\n"
        "/newaddress - Gera um novo endereço onchain\n"
        "/channelstatus - Verifica o status dos canais\n"
    )
    await update.message.reply_text(help_text)

# Comando /invoiceqr
@authorized_only
async def invoice_with_qr(update, context):
    try:
        args = update.message.text.split()[1:]
        amount, memo, time = args[0], args[1], args[2]
        
        hash, request, qr_image = generate_invoice_with_qr(amount, memo, time)
        if qr_image is None:
            await update.message.reply_text(f"{ERROR_EMOJI} {hash}")
        else:
            await update.message.reply_text(f"{PAY_EMOJI} Total Invoice: {amount} sats\nMemo: {memo}")
            await update.message.reply_text(f"{SUCCESS_EMOJI} Payment Hash: {hash}")
            await update.message.reply_text(f"{MONEY_EMOJI} Invoice:\n\n{request}\n", parse_mode=ParseMode.MARKDOWN)
            await context.bot.send_photo(update.message.chat_id, qr_image, caption="QR Code da Invoice")
            await update.message.reply_text(f"{ATTENTION_EMOJI} Expira em {(int(time)/3600):.2f} horas")
    except IndexError:
        await update.message.reply_text(f"{ATTENTION_EMOJI} Forneça o valor, mensagem e tempo de expiração (em segundos). Ex: /invoiceqr 100000 pagamento 3600")

# Comando /pay
@authorized_only
async def pay_command(update, context):
    try:
        payment_request = update.message.text.split()[1]
        await update.message.reply_text(f"{PAY_EMOJI} Pagando invoice: {payment_request}")
        pay_invoice_cmd = f"lncli payinvoice {payment_request} --force"
        result = subprocess.run(pay_invoice_cmd, shell=True, capture_output=True, text=True)
        output = result.stdout.strip()
        if 'invoice expired' in output:
            await update.message.reply_text(f"{ATTENTION_EMOJI} Invoice expirada")
        elif 'invoice is already paid' in output:
            await update.message.reply_text(f"{ERROR_EMOJI} Invoice já paga")
        elif 'FAILURE_REASON_TIMEOUT' in output:
            await update.message.reply_text(f"💤 Tempo esgotado. Tente novamente")
        else:
            await update.message.reply_text(f"{SUCCESS_EMOJI} Invoice paga com sucesso")
            await send_long_message(update.message.chat_id, output, context)
    except IndexError:
        await update.message.reply_text(f"{ATTENTION_EMOJI} Forneça o payment_request. Ex: /pay <payment_request>")
    except Exception as e:
        await update.message.reply_text(f"{ERROR_EMOJI} Erro: {e}")

# Handler para pagamento via QR code (fotos)
@authorized_only
async def pay_from_qr(update, context):
    if update.message.photo:
        file_info = await context.bot.get_file(update.message.photo[-1].file_id)
        downloaded_file = await file_info.download_as_bytearray()
        
        temp_image_path = "temp_qr.png"
        with open(temp_image_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        
        payment_request = decode_qr_from_image(temp_image_path)
        if payment_request:
            await update.message.reply_text(f"{PAY_EMOJI} Pagando invoice: {payment_request}")
            pay_invoice_cmd = f"lncli payinvoice {payment_request} --force"
            try:
                result = subprocess.run(pay_invoice_cmd, shell=True, capture_output=True, text=True)
                output = result.stdout.strip()
                if 'invoice expired' in output:
                    await update.message.reply_text(f"{ATTENTION_EMOJI} Invoice expirada")
                elif 'invoice is already paid' in output:
                    await update.message.reply_text(f"{ERROR_EMOJI} Invoice já paga")
                elif 'FAILURE_REASON_TIMEOUT' in output:
                    await update.message.reply_text(f"💤 Tempo esgotado. Tente novamente")
                else:
                    await update.message.reply_text(f"{SUCCESS_EMOJI} Invoice paga com sucesso")
                    await send_long_message(update.message.chat_id, output, context)
            except Exception as e:
                await update.message.reply_text(f"{ERROR_EMOJI} Erro: {e}")
        else:
            await update.message.reply_text(f"{ERROR_EMOJI} Não foi possível decodificar o QR code")
        
        os.remove(temp_image_path)
    else:
        await update.message.reply_text(f"{ATTENTION_EMOJI} Envie uma foto do QR code para pagar.")

# Comando /sendonchain
@authorized_only
async def send_onchain(update, context):
    try:
        args = update.message.text.split()[1:]
        address, amount, fee_rate = args[0], args[1], args[2]
        
        send_cmd = f"lncli sendcoins --addr {address} --amt {amount} --sat_per_vbyte {fee_rate}"
        await update.message.reply_text(f"{PAY_EMOJI} Enviando {amount} sats para {address} com taxa de {fee_rate} sat/vB")
        
        result = subprocess.run(send_cmd, shell=True, capture_output=True, text=True)
        output = result.stdout.strip()
        if "txid" in output:
            txid = json.loads(output)["txid"]
            await update.message.reply_text(f"{SUCCESS_EMOJI} Transação enviada. TXID: {txid}")
        else:
            await update.message.reply_text(f"{ERROR_EMOJI} Erro: {output}")
    except IndexError:
        await update.message.reply_text(f"{ATTENTION_EMOJI} Forneça o endereço, valor e taxa (sat/vB). Ex: /sendonchain bc1... 100000 10")
    except Exception as e:
        await update.message.reply_text(f"{ERROR_EMOJI} Erro: {e}")

# Comando /newaddress
@authorized_only
async def new_address(update, context):
    result = subprocess.run("lncli newaddress p2wkh", shell=True, capture_output=True, text=True)
    output = json.loads(result.stdout.strip())
    address = output["address"]
    await update.message.reply_text(f"{SUCCESS_EMOJI} Novo endereço: {address}")

# Comando /channelstatus
@authorized_only
async def channel_status(update, context):
    result = subprocess.run("lncli listchannels", shell=True, capture_output=True, text=True)
    await update.message.reply_text(f"{SUCCESS_EMOJI} Status dos Canais:\n\n{result.stdout}\n", parse_mode=ParseMode.MARKDOWN)

# Crie o Application com seu token
TOKEN = "YOUR TELEGRAM TOKEN"
application = Application.builder().token(TOKEN).build()

# Adicione os handlers
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("invoiceqr", invoice_with_qr))
application.add_handler(CommandHandler("pay", pay_command))
application.add_handler(MessageHandler(filters.PHOTO, pay_from_qr))
application.add_handler(CommandHandler("sendonchain", send_onchain))
application.add_handler(CommandHandler("newaddress", new_address))
application.add_handler(CommandHandler("channelstatus", channel_status))

# Inicie o bot
application.run_polling()
