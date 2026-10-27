import os
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_migrate import Migrate

from db import db
from models import Book, Member
from sqlalchemy.exc import IntegrityError

load_dotenv()

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    os.getenv("DATABASE_URL") or "sqlite:///books.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate = Migrate(app, db)


def buscar_livro(book_id):
    try:
        identificador = UUID(book_id)
    except ValueError:
        return None

    return db.session.get(Book, identificador)


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

    resultado["description"] = descricao.strip()

    return resultado, None


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
    db.session.commit()

    return "", 204

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

    # Verificação básica de formato para este projeto de estudos.
    partes = email.split("@")

    if (
        len(email) > 200
        or len(partes) != 2
        or not partes[0]
        or not partes[1]
        or any(caractere.isspace() for caractere in email)
    ):
        return jsonify({"erro": "Informe um e-mail válido."}), 400

    leitor = Member(name=nome, email=email)

    db.session.add(leitor)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"erro": "Este e-mail já está cadastrado."}), 409

    return jsonify(leitor.to_dict()), 201

if __name__ == "__main__":
    app.run()