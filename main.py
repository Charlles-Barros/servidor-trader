import io
import os
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from PIL import Image
from google import genai
from supabase import create_client, Client

app = FastAPI()

# Configuração Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configuração Gemini API
GEMINI_KEYS_ENV = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
GEMINI_KEYS = [k.strip() for k in GEMINI_KEYS_ENV.split(",") if k.strip()]

# Lista de modelos exata que já funcionava no seu projeto
MODELOS_GEMINI = [
    "gemini-3.7-flash",
    "gemini-flash-latest",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-pro-latest"
]

PROMPT_ANALISE = (
    "Análise RÁPIDA de Price Action e Suporte/Resistência.\n"
    "Examine o gráfico na imagem:\n"
    "1. Identifique o ativo visível.\n"
    "2. Recomende a melhor operação (2M ou 5M em tendências claras).\n"
    "3. Calcule a probabilidade (30% a 95%).\n\n"
    "Responda EXATAMENTE neste formato sem formatação extra:\n"
    "Ativo: [NOME] | Tempo operação: [2M ou 5M] | Ordem: [CALL ou PUT] | Probabilidade: [XX%]"
)

class LoginData(BaseModel):
    email: str
    senha: str

@app.get("/")
def home():
    return {"status": "Servidor Megalodon Online"}

@app.post("/login")
async def login(dados: LoginData):
    try:
        res = supabase.table("usuarios").select("*").eq("email", dados.email.strip()).execute()
        
        if not res.data:
            return {"autenticado": False, "mensagem": "E-mail ou senha incorretos."}
        
        usuario = res.data[0]
        
        if usuario.get("senha_hash") != dados.senha.strip():
            return {"autenticado": False, "mensagem": "E-mail ou senha incorretos."}
        
        vencimento_str = usuario.get("vencimento_licenca")
        if vencimento_str:
            vencimento = datetime.fromisoformat(vencimento_str.replace("Z", "+00:00"))
            agora = datetime.now(timezone.utc)
            
            if agora > vencimento:
                return {"autenticado": False, "mensagem": "Sua licença expirou!"}
            
            dias_restantes = (vencimento - agora).days
        else:
            dias_restantes = 0

        return {"autenticado": True, "dias_restantes": dias_restantes}

    except Exception as e:
        print(f"Erro no login: {e}")
        return {"autenticado": False, "mensagem": "Erro interno no servidor."}

@app.post("/analisar")
async def analisar(file: UploadFile = File(...)):
    if not GEMINI_KEYS:
        print("ERRO: Nenhuma chave GEMINI_API_KEY configurada.")
        raise HTTPException(status_code=500, detail="Nenhuma API Key do Gemini configurada.")

    contents = await file.read()
    image = Image.open(io.BytesIO(contents))

    for api_key in GEMINI_KEYS:
        client_gemini = genai.Client(api_key=api_key)
        for modelo in MODELOS_GEMINI:
            try:
                response = client_gemini.models.generate_content(
                    model=modelo,
                    contents=[PROMPT_ANALISE, image]
                )
                if response.text:
                    return {"analise": response.text.strip()}
            except Exception as e:
                print(f"Falha no modelo '{modelo}': {e}")
                continue

    raise HTTPException(status_code=500, detail="Falha no processamento da imagem por todas as chaves Gemini.")
