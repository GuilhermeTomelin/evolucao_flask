"""Regras de exemplares, associação de contas e circulação de livros."""
from datetime import timedelta
from uuid import UUID

from flask import g, jsonify, request
from sqlalchemy.exc import IntegrityError

from db import db
from models import Book, Copy, Loan, Member, User, UserMember
from models.loan import utc_now


def find(model, value):
    if not isinstance(value, str):
        return None
    try:
        identifier = UUID(value)
    except ValueError:
        return None
    return db.session.get(model, identifier)


def available_copies(book_id):
    occupied = db.select(Loan.id).where(
        Loan.copy_id == Copy.id, Loan.returned_at.is_(None)).exists()
    return db.select(Copy).where(Copy.book_id == book_id, ~occupied).order_by(Copy.inventory_code)


def register_circulation(app):
    @app.get("/books/<book_id>/copies")
    def listar_exemplares(book_id):
        book = find(Book, book_id)
        if book is None:
            return jsonify(erro="Livro não encontrado."), 404
        copies = db.session.scalars(db.select(Copy).where(
            Copy.book_id == book.id).order_by(Copy.inventory_code)).all()
        return jsonify([copy.to_dict() for copy in copies])

    @app.post("/books/<book_id>/copies")
    def cadastrar_exemplar(book_id):
        book = find(Book, book_id)
        if book is None:
            return jsonify(erro="Livro não encontrado."), 404
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {"inventory_code"}:
            return jsonify(erro="Envie apenas inventory_code em um objeto JSON."), 400
        code = data["inventory_code"]
        if not isinstance(code, str) or not 1 <= len(code.strip()) <= 100:
            return jsonify(erro="inventory_code deve ter de 1 a 100 caracteres."), 400
        copy = Copy(book_id=book.id, inventory_code=code.strip())
        db.session.add(copy)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(erro="Código de patrimônio já cadastrado ou livro indisponível."), 409
        return jsonify(copy.to_dict()), 201

    @app.get("/users")
    def listar_contas():
        users = db.session.scalars(db.select(User).order_by(User.name)).all()
        return jsonify([user.to_dict() for user in users])

    @app.put("/users/<user_id>/member")
    def associar_leitor(user_id):
        user = find(User, user_id)
        if user is None:
            return jsonify(erro="Conta não encontrada."), 404
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {"member_id"}:
            return jsonify(erro="Envie apenas member_id em um objeto JSON."), 400
        member = find(Member, data["member_id"])
        if member is None:
            return jsonify(erro="Leitor não encontrado."), 404
        current = user.member_id
        if current == member.id:
            return jsonify(user.to_dict())
        if current is not None:
            return jsonify(erro="Esta conta já tem leitor associado. O vínculo é fixo nesta versão para preservar o acesso ao histórico."), 409
        db.session.add(UserMember(user_id=user.id, member_id=member.id))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(erro="A conta ou o leitor já possui vínculo."), 409
        return jsonify(user.to_dict())

    @app.post("/loans")
    def emprestar():
        member_id = g.usuario.member_id
        if member_id is None:
            return jsonify(erro="Sua conta não está associada a um leitor. Peça ao administrador para fazer a associação em Contas e leitores."), 403
        data = request.get_json(silent=True)
        # Nunca aceitamos identidade, datas ou prazo informados pelo cliente.
        if not isinstance(data, dict) or set(data) not in ({"book_id"}, {"copy_id"}):
            return jsonify(erro="Envie somente book_id ou somente copy_id. O leitor e o prazo são definidos pelo servidor."), 400
        if "book_id" in data:
            book = find(Book, data["book_id"])
            if book is None:
                return jsonify(erro="Livro não encontrado."), 404
            copy = db.session.scalar(available_copies(book.id).limit(1))
        else:
            copy = find(Copy, data["copy_id"])
            if copy is None:
                return jsonify(erro="Exemplar não encontrado."), 404
        if copy is None:
            return jsonify(erro="Nenhum exemplar disponível para este livro."), 409
        now = utc_now()
        loan = Loan(copy_id=copy.id, member_id=member_id,
                    borrowed_at=now, due_at=now + timedelta(days=14))
        db.session.add(loan)
        try:
            # A consulta de disponibilidade ajuda a tela; o índice único é a
            # garantia definitiva, inclusive quando duas requisições concorrem.
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(erro="Exemplar indisponível. Atualize o catálogo e tente novamente."), 409
        return jsonify(loan.to_dict()), 201

    @app.get("/loans")
    def listar_emprestimos():
        scope = request.args.get("scope", "mine")
        if set(request.args) - {"scope"} or scope not in {"mine", "all"}:
            return jsonify(erro="Use scope=mine ou scope=all."), 400
        query = db.select(Loan).order_by(Loan.borrowed_at.desc(), Loan.id)
        if scope == "all":
            if not g.usuario.can_manage_loans:
                return jsonify(erro="Acesso exclusivo do atendente ou administrador."), 403
        else:
            member_id = g.usuario.member_id
            if member_id is None:
                return jsonify([])
            query = query.where(Loan.member_id == member_id)
        return jsonify([loan.to_dict() for loan in db.session.scalars(query).all()])

    @app.get("/loans/<loan_id>")
    def consultar_emprestimo(loan_id):
        loan = find(Loan, loan_id)
        # Não revelar a existência de empréstimos de outro leitor.
        if loan is None or (not g.usuario.can_manage_loans and loan.member_id != g.usuario.member_id):
            return jsonify(erro="Empréstimo não encontrado."), 404
        return jsonify(loan.to_dict())

    @app.post("/loans/<loan_id>/return")
    def devolver(loan_id):
        loan = find(Loan, loan_id)
        if loan is None or (not g.usuario.can_manage_loans and loan.member_id != g.usuario.member_id):
            return jsonify(erro="Empréstimo não encontrado."), 404
        # Comparação e alteração em um só comando: duas devoluções simultâneas
        # não podem ambas ter sucesso. Não deletamos a linha do empréstimo.
        result = db.session.execute(db.update(Loan).where(
            Loan.id == loan.id, Loan.returned_at.is_(None)
        ).values(returned_at=utc_now()))
        if result.rowcount != 1:
            db.session.rollback()
            return jsonify(erro="Este empréstimo já foi devolvido."), 409
        db.session.commit()
        return jsonify(loan.to_dict())
