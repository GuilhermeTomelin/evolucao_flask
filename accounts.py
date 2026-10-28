"""Cadastro público e gestão administrativa de acesso (etapa A)."""
from flask import g, jsonify, request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from circulation import find
from db import db
from models import Member, User, UserMember
from models.user import ROLES


def update_access(user, **values):
    """Compara a versão e revalida o administrador no próprio UPDATE.

    Evita decisões simultâneas conflitantes e impede que dois administradores
    removam um ao outro usando a autorização antiga de uma requisição.
    """
    actor = aliased(User)
    actor_allowed = db.select(actor.id).where(
        actor.id == g.usuario.id, actor.role == "admin",
        actor.status == "approved", actor.active.is_(True),
        actor.auth_version == g.usuario.auth_version,
    ).exists()
    result = db.session.execute(
        db.update(User).where(
            User.id == user.id, User.auth_version == user.auth_version,
            User.status == user.status, actor_allowed,
        ).values(**values, auth_version=User.auth_version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.session.rollback()
        return False
    return True


def register_accounts(app, email_valido):
    @app.post("/auth/register")
    def solicitar_cadastro():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {"name", "email", "password"}:
            return jsonify(erro="Envie apenas name, email e password. O cadastro público sempre cria um leitor pendente."), 400
        name, email, password = data["name"], data["email"], data["password"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 150:
            return jsonify(erro="O nome deve ter de 1 a 150 caracteres."), 400
        if not isinstance(email, str) or not email_valido(email.strip()):
            return jsonify(erro="Informe um e-mail válido."), 400
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            return jsonify(erro="A senha deve ter de 8 a 128 caracteres."), 400
        user = User(name=name.strip(), email=email.strip().lower(),
                    role="reader", status="pending", active=False)
        user.set_password(password)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(erro="Este e-mail já possui uma conta. Procure o administrador se precisar de acesso."), 409
        # Não inicia sessão nem cria/associa leitor por coincidência de e-mail.
        return jsonify(mensagem="Solicitação recebida. Aguarde a aprovação do administrador.",
                       status="pending"), 201

    @app.post("/users/<user_id>/approve")
    def aprovar_conta(user_id):
        user = find(User, user_id)
        if user is None:
            return jsonify(erro="Conta não encontrada."), 404
        if user.status not in ("pending", "rejected", "blocked"):
            return jsonify(erro="Esta conta já está aprovada."), 409
        data = request.get_json(silent=True)
        if data is None and not request.get_data():
            data = {}
        if not isinstance(data, dict) or set(data) not in (set(), {"member_id"}, {"create_member"}):
            return jsonify(erro="Envie member_id ou create_member: true. Não envie ambos."), 400
        current = user.member_id
        member = None
        create = False
        if current:
            if data and data != {"member_id": str(current)}:
                return jsonify(erro="Esta conta já possui vínculo fixo. Aprove sem substituir o leitor."), 409
        elif set(data) == {"member_id"}:
            member = find(Member, data["member_id"])
            if member is None:
                return jsonify(erro="Leitor não encontrado."), 404
        elif data.get("create_member") is True:
            create = True
        else:
            return jsonify(erro="Escolha um leitor existente ou confirme a criação de um novo leitor."), 400
        # A atualização e a associação pertencem à mesma transação.
        if not update_access(user, status="approved", active=True):
            return jsonify(erro="A conta ou suas permissões mudaram. Atualize a página."), 409
        try:
            if not current:
                if create:
                    member = Member(name=user.name, email=user.email)
                    db.session.add(member)
                    db.session.flush()
                db.session.add(UserMember(user_id=user.id, member_id=member.id))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify(erro="Leitor já associado ou e-mail de leitor existente. Confira a identidade e escolha explicitamente um leitor livre."), 409
        return jsonify(user.to_dict())

    def restrict_account(user_id, target_status):
        data = request.get_json(silent=True)
        if request.get_data() and data != {}:
            return jsonify(erro="Esta operação não recebe campos."), 400
        user = find(User, user_id)
        if user is None:
            return jsonify(erro="Conta não encontrada."), 404
        if user.id == g.usuario.id:
            return jsonify(erro="Você não pode bloquear ou rejeitar a própria conta."), 409
        expected = "pending" if target_status == "rejected" else "approved"
        if user.status != expected:
            return jsonify(erro="Transição de situação não permitida. Atualize a lista de contas."), 409
        if not update_access(user, status=target_status, active=False):
            return jsonify(erro="A conta ou suas permissões mudaram. Atualize a página."), 409
        db.session.commit()
        return jsonify(user.to_dict())

    @app.post("/users/<user_id>/reject")
    def rejeitar_conta(user_id):
        return restrict_account(user_id, "rejected")

    @app.post("/users/<user_id>/block")
    def bloquear_conta(user_id):
        return restrict_account(user_id, "blocked")

    @app.put("/users/<user_id>/role")
    def atribuir_papel(user_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {"role"} or data["role"] not in ROLES:
            return jsonify(erro="Envie role: reader, attendant ou admin."), 400
        user = find(User, user_id)
        if user is None:
            return jsonify(erro="Conta não encontrada."), 404
        if user.id == g.usuario.id:
            return jsonify(erro="Peça a outro administrador para alterar seu papel."), 409
        if user.status != "approved" or not user.active:
            return jsonify(erro="Aprove a conta antes de atribuir um papel."), 409
        if user.role == data["role"]:
            return jsonify(user.to_dict())
        if not update_access(user, role=data["role"], is_admin=data["role"] == "admin"):
            return jsonify(erro="A conta ou suas permissões mudaram. Atualize a página."), 409
        db.session.commit()
        return jsonify(user.to_dict())
