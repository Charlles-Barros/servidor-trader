import io
import os
import re
import secrets
import string
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, File, HTTPException, UploadFile, Header, Request
from pydantic import BaseModel
from PIL import Image
from google import genai
from google.genai import types
from supabase import create_client, Client

app = FastAPI(title="Megalodon Trader API - Server Central")

# =========================================================
# CONFIGURAÇÕES SEGURAS (Lendo das Variáveis de Ambiente)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "MEGALODON_SECRET_123")

# Validação das chaves do Supabase
if not SUPABASE_URL or not SUPABASE_KEY:
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# CHAVES DA API GEMINI (Separadas por vírgula no Render)
env_keys = os.getenv("GEMINI_API_KEYS", "")
API_KEYS = [k.strip() for k in env_keys.split(",") if k.strip()]

# MODELOS ATIVOS
MODELOS_DISPONIVEIS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest"
]

# =========================================================
key_index = 0

def get_client():
    global key_index
    if not API_KEYS:
        raise HTTPException(status_code=500, detail="Nenhuma chave API do Gemini configurada.")
    chave_atual = API_KEYS[key_index % len(API_KEYS)].strip()
    key_index += 1
    return genai.Client(api_key=chave_atual)

def gerar_senha_temporaria(tamanho=8):
    caracteres = string.ascii_letters + string.digits
    return ''.join(secrets.choice(caracteres) for _ in range(tamanho))

class LoginRequest(BaseModel):
    email: str
    senha: str

@app.get("/")
def status_server():
    return {"status": "online", "servico": "Megalodon Trader API"}

# 1. Rota de Login do Cliente no App Flutuante
@app.post("/login")
def login(dados: LoginRequest):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
        
    res = supabase.table("usuarios").select("senha_hash, vencimento_licenca").eq("email", dados.email).execute()
    
    if not res.data:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")
        
    user = res.data[0]
    if user["senha_hash"] != dados.senha:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")
        
    vencimento = datetime.fromisoformat(user["vencimento_licenca"].replace("Z", "+00:00"))
    agora = datetime.now(timezone.utc)
    dias_restantes = (vencimento - agora).days
    if agora > vencimento:
        return {
            "autenticado": False,
            "mensagem": "Licença expirada.",
            "dias_restantes": 0
        }
    return {
        "autenticado": True,
        "mensagem": "Login realizado com sucesso!",
        "dias_restantes": dias_restantes
    }

# 2. Rota do Webhook da Kiwify
@app.post("/webhook/kiwify")
async def webhook_kiwify(request: Request, token: str = None):
    if token != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Token de webhook inválido.")
    
    payload = await request.json()
    
    order_status = payload.get("order_status")
    customer = payload.get("Customer", {})
    email = customer.get("email")
    if not email or order_status != "paid":
        return {"status": "ignorado", "motivo": "Pagamento não aprovado ou e-mail ausente."}
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
    res = supabase.table("usuarios").select("*").eq("email", email).execute()
    agora = datetime.now(timezone.utc)
    if res.data:
        user = res.data[0]
        venc_atual = datetime.fromisoformat(user["vencimento_licenca"].replace("Z", "+00:00"))
        base_calculo = venc_atual if venc_atual > agora else agora
        novo_vencimento = base_calculo + timedelta(days=30)
        supabase.table("usuarios").update({
            "vencimento_licenca": novo_vencimento.isoformat()
        }).eq("email", email).execute()
        return {"status": "sucesso", "acao": "licenca_renovada", "email": email}
    else:
        senha_temp = gerar_senha_temporaria()
        novo_vencimento = agora + timedelta(days=30)
        supabase.table("usuarios").insert({
            "email": email,
            "senha_hash": senha_temp,
            "vencimento_licenca": novo_vencimento.isoformat()
        }).execute()
        return {
            "status": "sucesso",
            "acao": "usuario_criado",
            "email": email,
            "senha_provisoria": senha_temp
        }

# 3. Rota de Análise do Gráfico com Visão Computacional
@app.post("/analisar")
def analisar_grafico(
    email_usuario: str = Header(..., alias="email-usuario"), 
    file: UploadFile = File(...)
):
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
    res = supabase.table("usuarios").select("vencimento_licenca").eq("email", email_usuario).execute()
    
    if not res.data:
        raise HTTPException(status_code=403, detail="Acesso negado. Usuário não encontrado.")
        
    vencimento = datetime.fromisoformat(res.data[0]["vencimento_licenca"].replace("Z", "+00:00"))
    agora = datetime.now(timezone.utc)
    
    if agora > vencimento:
        raise HTTPException(
            status_code=403, 
            detail="Sua licença expirou. Renove para continuar recebendo sinais."
        )
    dias_restantes = (vencimento - agora).days
    try:
        contents = file.file.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
        img.thumbnail((800, 800))
        prompt = (
            "Examine o gráfico. Responda em UMA ÚNICA LINHA SEM QUEBRAS:\n"
            "Ativo: [NOME] | Tempo operação: [2M ou 5M] | Ordem: [CALL ou PUT] | Probabilidade: [XX%]"
        )
        response = None
        erros_detalhados = []
        for modelo in MODELOS_DISPONIVEIS:
            try:
                client = get_client()
                res_temp = client.models.generate_content(
                    model=modelo,
                    contents=[prompt, img]
                )
                if res_temp and res_temp.text:
                    response = res_temp
                    break
            except Exception as e_model:
                erros_detalhados.append(f"{modelo}: {str(e_model)}")
        if not response or not response.text:
            erro_final = " | ".join(erros_detalhados) if erros_detalhados else "Nenhum modelo respondeu"
            raise HTTPException(status_code=500, detail=f"Erro na IA -> {erro_final}")
        resultado_texto = response.text.strip().replace("\n", " ")
        ordem = "CALL" if "CALL" in resultado_texto.upper() else ("PUT" if "PUT" in resultado_texto.upper() else "NEUTRO")
        
        match_prob = re.search(r"Probabilidade:\s*(\d+)%", resultado_texto)
        probabilidade = int(match_prob.group(1)) if match_prob else 0
        return {
            "status": "sucesso",
            "dias_licenca_restantes": dias_restantes,
            "sinal_completo": resultado_texto,
            "ordem": ordem,
            "probabilidade": probabilidade
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro de processamento: {str(e)}")
