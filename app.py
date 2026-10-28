from datetime import timedelta
import os
from uuid import UUID

import click
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, session
from flask_migrate import Migrate
from sqlalchemy.exc import IntegrityError, OperationalError

from db import db
from models import Book, Member, User
from circulation import register_circulation
from accounts import register_accounts


if os.getenv("FLASK_SKIP_DOTENV") != "1":
    load_dotenv()


app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError("Configure SECRET_KEY no arquivo .env.")

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Em produção (HTTPS), defina SESSION_COOKIE_SECURE=true no .env.
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    os.getenv("DATABASE_URL") or "sqlite:///books.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"hide_parameters": True}

db.init_app(app)
migrate = Migrate(app, db)
register_circulation(app)


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def buscar_livro(book_id):
    try:
        identificador = UUID(book_id)
    except ValueError:
        return None

    return db.session.get(Book, identificador)


def email_valido(email):
    # Verificação básica de formato para este projeto de estudos.
    partes = email.split("@")

    return not (
        len(email) > 200
        or len(partes) != 2
        or not partes[0]
        or not partes[1]
        or any(caractere.isspace() for caractere in email)
    )


register_accounts(app, email_valido)


def validar_dados():
    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return None, "Envie um objeto JSON."

    permitidos = {"title", "author", "description"}

    if set(dados) - permitidos:
        return None, "Use apenas title, author e description."

    resultado = {}

    for campo, limite in [("title", 200), ("author", 150)]:
        valor = dados.get(campo)

        if not isinstance(valor, str):
            return None, f"O campo {campo} deve ser texto."

        valor = valor.strip()

        if not valor or len(valor) > limite:
            return None, f"{campo} deve ter de 1 a {limite} caracteres."

        resultado[campo] = valor

    descricao = dados.get("description", "")

    if not isinstance(descricao, str):
        return None, "description deve ser texto."

    descricao = descricao.strip()

    if len(descricao) > 2000:
        return None, "description deve ter até 2000 caracteres."

    resultado["description"] = descricao

    return resultado, None


# ---------------------------------------------------------------------------
# Controle de acesso
# ---------------------------------------------------------------------------

@app.before_request
def verificar_acesso():
    # Somente estas rotas são públicas.
    if request.endpoint in {"inicio", "login", "solicitar_cadastro"}:
        return None

    # Rota inexistente: deixa o Flask devolver o 404.
    if request.endpoint is None:
        return None

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"erro": "Faça login para continuar."}), 401

    try:
        identificador = UUID(user_id)
    except (ValueError, TypeError):
        session.clear()
        return jsonify({"erro": "Sessão inválida. Faça login novamente."}), 401

    usuario = db.session.get(User, identificador)

    if usuario is None or not usuario.active or usuario.status != "approved":
        session.clear()
        return jsonify({"erro": "Conta indisponível."}), 401

    # Cookies anteriores à etapa A usam versão 0 e continuam válidos.
    if session.get("auth_version", 0) != usuario.auth_version:
        session.clear()
        return jsonify({"erro": "Seu acesso foi alterado. Faça login novamente."}), 401

    g.usuario = usuario

    # Lista explícita: rotas novas não recebem permissão por acidente.
    reader_routes = {
        "minha_conta": {"GET", "HEAD"}, "logout": {"POST"},
        "listar_livros": {"GET", "HEAD"}, "consultar_livro": {"GET", "HEAD"},
        "emprestar": {"POST"}, "listar_emprestimos": {"GET", "HEAD"},
        "consultar_emprestimo": {"GET", "HEAD"}, "devolver": {"POST"},
    }
    admin_routes = {
        "cadastrar_livro": {"POST"}, "atualizar_livro": {"PUT"},
        "excluir_livro": {"DELETE"}, "listar_leitores": {"GET", "HEAD"},
        "cadastrar_leitor": {"POST"}, "listar_contas": {"GET", "HEAD"},
        "associar_leitor": {"PUT"}, "listar_exemplares": {"GET", "HEAD"},
        "cadastrar_exemplar": {"POST"},
        "aprovar_conta": {"POST"}, "rejeitar_conta": {"POST"},
        "bloquear_conta": {"POST"}, "atribuir_papel": {"PUT"},
    }
    staff_routes = {"listar_exemplares": {"GET", "HEAD"}}
    staff_allowed = request.method in staff_routes.get(request.endpoint, set())
    allowed = request.method in reader_routes.get(request.endpoint, set())
    admin_allowed = request.method in admin_routes.get(request.endpoint, set())
    if not allowed and not (usuario.role == "admin" and admin_allowed) and not (usuario.can_manage_loans and staff_allowed):
        return jsonify({"erro": "Acesso exclusivo do administrador ou operação não permitida."}), 403



# ---------------------------------------------------------------------------
# Livros
# ---------------------------------------------------------------------------

@app.get("/")
def inicio():
    return jsonify({
        "mensagem": "API de livros",
        "recurso": "/books"
    })


@app.get("/books")
def listar_livros():
    consulta = db.select(Book).order_by(Book.title)
    livros = db.session.execute(consulta).scalars().all()

    return jsonify([livro.to_dict() for livro in livros])


@app.get("/books/<book_id>")
def consultar_livro(book_id):
    livro = buscar_livro(book_id)

    if livro is None:
        return jsonify({"erro": "Livro não encontrado."}), 404

    return jsonify(livro.to_dict())


@app.post("/books")
def cadastrar_livro():
    dados, erro = validar_dados()

    if erro:
        return jsonify({"erro": erro}), 400

    livro = Book(**dados)

    db.session.add(livro)
    db.session.commit()

    return jsonify(livro.to_dict()), 201


@app.put("/books/<book_id>")
def atualizar_livro(book_id):
    livro = buscar_livro(book_id)

    if livro is None:
        return jsonify({"erro": "Livro não encontrado."}), 404

    dados, erro = validar_dados()

    if erro:
        return jsonify({"erro": erro}), 400

    livro.title = dados["title"]
    livro.author = dados["author"]
    livro.description = dados["description"]

    db.session.commit()

    return jsonify(livro.to_dict())


@app.delete("/books/<book_id>")
def excluir_livro(book_id):
    livro = buscar_livro(book_id)

    if livro is None:
        return jsonify({"erro": "Livro não encontrado."}), 404

    db.session.delete(livro)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"erro": "Livro possui exemplares. A exclusão foi bloqueada para preservar os vínculos e o histórico."}), 409

    return "", 204


# ---------------------------------------------------------------------------
# Leitores
# ---------------------------------------------------------------------------

@app.get("/members")
def listar_leitores():
    consulta = db.select(Member).order_by(Member.name)
    leitores = db.session.execute(consulta).scalars().all()

    return jsonify([leitor.to_dict() for leitor in leitores])


@app.post("/members")
def cadastrar_leitor():
    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return jsonify({"erro": "Envie um objeto JSON."}), 400

    if set(dados) - {"name", "email"}:
        return jsonify({"erro": "Use apenas name e email."}), 400

    nome = dados.get("name")
    email = dados.get("email")

    if not isinstance(nome, str) or not nome.strip():
        return jsonify({"erro": "Informe o nome do leitor."}), 400

    if not isinstance(email, str):
        return jsonify({"erro": "Informe um e-mail."}), 400

    nome = nome.strip()
    email = email.strip().lower()

    if len(nome) > 150:
        return jsonify({"erro": "O nome deve ter até 150 caracteres."}), 400

    if not email_valido(email):
        return jsonify({"erro": "Informe um e-mail válido."}), 400

    leitor = Member(name=nome, email=email)

    db.session.add(leitor)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"erro": "Este e-mail já está cadastrado."}), 409

    return jsonify(leitor.to_dict()), 201


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

@app.post("/auth/login")
def login():
    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return jsonify({"erro": "Envie um objeto JSON."}), 400

    email = dados.get("email")
    senha = dados.get("password")

    if not isinstance(email, str) or not isinstance(senha, str):
        return jsonify({"erro": "Informe email e password."}), 400

    email = email.strip().lower()
    session.clear()

    usuario = db.session.execute(
        db.select(User).where(User.email == email)
    ).scalar_one_or_none()

    if (
        usuario is None
        or not usuario.check_password(senha)
    ):
        return jsonify({"erro": "E-mail ou senha inválidos."}), 401

    if usuario.status != "approved":
        messages = {
            "pending": "Cadastro pendente. Aguarde a aprovação do administrador.",
            "rejected": "Cadastro rejeitado. Procure o administrador.",
            "blocked": "Conta bloqueada. Procure o administrador.",
        }
        return jsonify(erro=messages.get(usuario.status, "Conta indisponível.")), 403
    if not usuario.active:
        return jsonify(erro="Conta indisponível. Procure o administrador."), 401

    session.clear()
    session["user_id"] = str(usuario.id)
    session["auth_version"] = usuario.auth_version
    session.permanent = True

    return jsonify({
        "mensagem": "Login realizado.",
        "user": usuario.to_dict()
    })


@app.get("/auth/me")
def minha_conta():
    return jsonify(g.usuario.to_dict())


@app.post("/auth/logout")
def logout():
    session.clear()
    return jsonify({"mensagem": "Você saiu da conta."})


# ---------------------------------------------------------------------------
# Tratamento de erros (sempre em JSON)
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def erro_404(_erro):
    return jsonify({"erro": "Rota não encontrada."}), 404


@app.errorhandler(405)
def erro_405(_erro):
    return jsonify({"erro": "Método não permitido nesta rota."}), 405


@app.errorhandler(OperationalError)
def erro_banco_ocupado(erro):
    db.session.rollback()
    if "locked" in str(erro.orig).lower() or "busy" in str(erro.orig).lower():
        return jsonify({"erro": "Banco ocupado por outra operação. Atualize a página e tente novamente."}), 409
    app.logger.error("Falha operacional do banco; confira a configuração e as migrações.")
    return jsonify({"erro": "Banco indisponível. Peça ao administrador para verificar as migrações."}), 503


@app.errorhandler(500)
def erro_500(_erro):
    db.session.rollback()
    return jsonify({"erro": "Erro interno do servidor."}), 500


# ---------------------------------------------------------------------------
# Comandos de terminal
# ---------------------------------------------------------------------------

@app.cli.command("create-user")
@click.option("--admin", is_flag=True, help="Criar administrador.")
def create_user(admin):
    """Cria uma conta pelo terminal do servidor."""
    nome = click.prompt("Nome").strip()
    email = click.prompt("E-mail").strip().lower()
    senha = click.prompt(
        "Senha",
        hide_input=True,
        confirmation_prompt=True
    )

    if not nome or len(nome) > 150:
        raise click.ClickException("O nome deve ter de 1 a 150 caracteres.")

    if not email_valido(email):
        raise click.ClickException("Informe um e-mail válido.")

    if len(senha) < 8:
        raise click.ClickException("Use uma senha com pelo menos 8 caracteres.")

    usuario = User(name=nome, email=email, is_admin=admin)
    usuario.set_password(senha)

    db.session.add(usuario)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise click.ClickException("Este e-mail já está cadastrado.")

    click.echo("Conta criada com sucesso.")


if __name__ == "__main__":
    app.run()