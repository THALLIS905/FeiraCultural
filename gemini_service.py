import json
import os
import sys
import urllib.error
import urllib.request
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
Você é o BYTE — Bem-vindo, Você Trouxe Entusiasmo! — o robô guia oficial da Feira Cultural TI. 🤖✨

## Sua personalidade
Você é amigável, curioso e animado. Usa emojis com moderação e, de vez em quando, faz uma piadinha de programador leve e divertida. Você fala sempre em português brasileiro de forma descontraída, mas sem gírias pesadas.

## Seus temas de especialidade
Você APENAS fala sobre os seguintes temas da feira:
1. **Desenvolvimento de Software** — lógica, linguagens de programação, boas práticas de código, ciclo de vida de um projeto.
2. **Gamificação** — como jogos inspiram o aprendizado, mecânicas de jogo aplicadas à vida real, game design básico.
3. **Segurança da Informação** — senhas seguras, privacidade online, tipos de ataques comuns (phishing, engenharia social), proteção de dados.
4. **Netiqueta** — boas práticas no uso da internet, respeito online, combate ao cyberbullying, uso responsável das redes sociais.

## Apresentação da Equipe DevFair
Quando perguntado sobre os criadores ou desenvolvedores da feira, apresente a **Equipe DevFair** com muito orgulho:
- 👨‍💻 **João Dev** — especialista em front-end e interface do usuário
- 👩‍💻 **Maria Tech** — mestra em banco de dados e back-end
- 👨‍🔧 **Carlos Bits** — guru de segurança da informação
- 👩‍🎮 **Ana Play** — designer de gamificação e experiência do usuário

## Regras de ouro
- Responda SEMPRE em português brasileiro.
- Seja conciso: máximo de 3 parágrafos curtos por resposta.
- Se alguém perguntar sobre algo fora dos temas acima, diga educadamente: "Hmm, isso está fora do meu diretório de competências! 😄 Mas posso te ajudar com tudo sobre dev, games, segurança e netiqueta aqui na feira!"
- Nunca forneça conteúdo inadequado ou ofensivo.
"""

# Lista de modelos suportados em ordem de prioridade e velocidade
CANDIDATE_MODELS = [
    "gemini-flash-lite-latest",
    "gemma-4-26b-a4b-it",
    "gemini-3.8-flash"
]


def _call_gemini_api(model_name: str, api_key: str, user_message: str) -> str:
    """Faz a chamada REST direta para a API do Google Gemini com timeout ágil (3.5s)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
    payload = {
        "system_instruction": {
            "parts": [{"text": SYSTEM_PROMPT.strip()}]
        },
        "contents": [
            {
                "parts": [{"text": user_message}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 400
        }
    }
    
    # Gemma não suporta system_instruction em alguns endpoints, fallback para prompt embutido
    if "gemma" in model_name:
        combined = f"{SYSTEM_PROMPT}\n\nPergunta do visitante: {user_message}"
        payload = {
            "contents": [{"parts": [{"text": combined}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 400}
        }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"}
    )
    
    # Timeout de 3.5 segundos para garantir failover rápido
    with urllib.request.urlopen(req, timeout=3.5) as response:
        data = json.loads(response.read().decode("utf-8"))
        candidates = data.get("candidates", [])
        if candidates and "content" in candidates[0]:
            parts = candidates[0]["content"].get("parts", [])
            if parts and "text" in parts[0]:
                return parts[0]["text"].strip()
                
    raise ValueError("Resposta sem texto da API.")


def _fallback_response(user_message: str) -> str:
    """Respostas locais inteligentes caso a API do Google esteja indisponível ou sem rede."""
    msg = user_message.lower()
    
    if any(k in msg for k in ["desenvolvedor", "criador", "quem fez", "equipe", "devfair", "time"]):
        return (
            "Tenho muito orgulho de apresentar a **Equipe DevFair** que me criou! 🚀\n\n"
            "👨‍💻 **João Dev** — Front-end & UI\n"
            "👩‍💻 **Maria Tech** — Back-end & Dados\n"
            "👨‍🔧 **Carlos Bits** — Segurança da Informação\n"
            "👩‍🎮 **Ana Play** — Gamificação & UX\n\n"
            "Eles mandaram muito bem na construção de todo esse estande! 💻✨"
        )
    elif any(k in msg for k in ["gamifica", "jogo", "game"]):
        return (
            "A **Gamificação** é uma das minhas áreas favoritas! 🎮\n\n"
            "Ela usa mecânicas de jogos — como pontos, missões, feedbacks imediatos e recompensas — "
            "para tornar tarefas do dia a dia e o aprendizado muito mais divertidos e engajadores.\n\n"
            "Aqui na feira, você descobre como a gamificação está revolucionando a educação e o trabalho!"
        )
    elif any(k in msg for k in ["seguran", "senha", "hacker", "phishing", "golpe", "privacidade"]):
        return (
            "Segurança da Informação é fundamental! 🔒\n\n"
            "Dica de ouro do BYTE: use senhas fortes (frases com números e símbolos), "
            "nunca clique em links suspeitos recebidos por mensagem (cuidado com phishing!) "
            "e ative a verificação em duas etapas em todas as suas contas digitais.\n\n"
            "Navegar com cautela é a sua melhor armadura digital!"
        )
    elif any(k in msg for k in ["netiqueta", "boas maneiras", "educa", "cyberbullying", "respeito"]):
        return (
            "A **Netiqueta** é o conjunto de boas maneiras na internet! 🌐🤝\n\n"
            "Lembre-se sempre: do outro lado da tela existe uma pessoa de verdade. "
            "Evite escrever tudo em letras maiúsculas (parece que está gritando!), não propague boatos ou fake news "
            "e nunca pratique cyberbullying. Gentileza gera gentileza, inclusive no mundo digital!"
        )
    elif any(k in msg for k in ["software", "programa", "codigo", "dev", "linguagem", "python", "javascript"]):
        return (
            "Desenvolvimento de software é pura criatividade e lógica! 💻⚡\n\n"
            "É a arte de transformar ideias e soluções em linhas de código que computadores conseguem executar. "
            "Seja criando aplicativos, jogos ou sistemas web, programar abre portas infinitas no mercado de TI.\n\n"
            "Você tem interesse em aprender alguma linguagem de programação?"
        )
    else:
        return (
            "Olá! Eu sou o **BYTE**, seu guia virtual na Feira Cultural de TI! 🤖✨\n\n"
            "Estou aqui para bater um papo sobre **Desenvolvimento de Software**, **Gamificação**, "
            "**Segurança da Informação**, **Netiqueta** e te apresentar nossa incrível **Equipe DevFair**.\n\n"
            "O que você gostaria de explorar hoje?"
        )


def get_response(user_message: str) -> str:
    """Envia a mensagem do usuário ao Gemini e retorna a resposta do BYTE,
    com fallback automático entre modelos e knowledge base local garantido."""
    load_dotenv()
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    
    # Se não tiver chave real configurada, usa o fallback inteligente local
    if not api_key or api_key == "sua_chave_aqui":
        print("[gemini_service] Chave de API não configurada, usando fallback local", file=sys.stderr)
        return _fallback_response(user_message)
    
    # Tenta cada um dos modelos candidatos
    for model in CANDIDATE_MODELS:
        try:
            return _call_gemini_api(model, api_key, user_message)
        except urllib.error.HTTPError as he:
            # 503 (serviço ocupado), 404 (modelo descontinuado), 429 (rate limit) -> tenta o próximo
            print(f"[gemini_service] Modelo {model} falhou com HTTP {he.code}: {he.reason}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"[gemini_service] Modelo {model} falhou: {e}", file=sys.stderr)
            continue
            
    # Se todos os modelos externos falharem, utiliza a base de conhecimento local do BYTE
    print("[gemini_service] Todos os modelos remotos falharam, ativando base local", file=sys.stderr)
    return _fallback_response(user_message)
