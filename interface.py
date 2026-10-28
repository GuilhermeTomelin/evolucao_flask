from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st

API_URL = "http://127.0.0.1:5000"
ROLE_LABELS = {"reader": "Leitor", "attendant": "Atendente", "admin": "Administrador"}

st.set_page_config(page_title="Minha Biblioteca", page_icon="📚", layout="wide")

# Nunca usar cache global para Session: cookies pertencem a cada sessão da tela.
if "api" not in st.session_state:
    st.session_state.api = requests.Session()


def limpar_login():
    st.session_state.api.close()
    st.session_state.api = requests.Session()
    st.session_state.pop("usuario", None)


def chamar_api(metodo, rota, **kwargs):
    try:
        response = st.session_state.api.request(
            metodo, f"{API_URL}{rota}", timeout=10, **kwargs)
    except requests.RequestException:
        st.error("Não foi possível acessar a API. Confira se o Flask está rodando na porta 5000.")
        return None
    if response.status_code == 401 and rota != "/auth/login":
        limpar_login()
        st.session_state.aviso = "Sua sessão terminou. " + mensagem_erro(response)
        st.rerun()
    return response


def mensagem_erro(resposta):
    try:
        data = resposta.json()
        if isinstance(data, dict):
            return data.get("erro", "Não foi possível concluir.")
    except ValueError:
        pass
    return "O servidor retornou uma resposta inesperada."


def consultar(rota):
    response = chamar_api("GET", rota)
    if response is None:
        return None
    if response.status_code != 200:
        st.error(mensagem_erro(response))
        return None
    return response.json()


def executar(metodo, rota, mensagem, **kwargs):
    response = chamar_api(metodo, rota, **kwargs)
    if response is None:
        return
    if response.status_code in (200, 201, 204):
        st.session_state.sucesso = mensagem
        st.rerun()
    st.error(mensagem_erro(response))


def data_local(value):
    if not value:
        return "—"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")


if "aviso" in st.session_state:
    st.warning(st.session_state.pop("aviso"))

if "usuario" in st.session_state:
    user = consultar("/auth/me")
    if user is None:
        st.stop()
    st.session_state.usuario = user

if "usuario" not in st.session_state:
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.title("📚 Minha Biblioteca")
        st.write("Entre na sua conta para explorar o catálogo.")
        with st.form("login"):
            email = st.text_input("E-mail")
            password = st.text_input("Senha", type="password")
            submit = st.form_submit_button("Entrar")
        if submit:
            if not email.strip() or not password:
                st.warning("Preencha o e-mail e a senha.")
            else:
                response = chamar_api("POST", "/auth/login",
                                      json={"email": email.strip(), "password": password})
                if response is not None:
                    if response.status_code == 200:
                        st.session_state.usuario = response.json()["user"]
                        st.rerun()
                    st.error(mensagem_erro(response))
        with st.expander("Solicitar cadastro"):
            st.write("Novos cadastros ficam pendentes. O administrador precisa aprovar seu acesso.")
            with st.form("register"):
                register_name = st.text_input("Nome completo", max_chars=150)
                register_email = st.text_input("E-mail do cadastro", max_chars=200)
                register_password = st.text_input("Senha do cadastro", type="password", max_chars=128)
                register_confirmation = st.text_input("Confirme a senha", type="password", max_chars=128)
                register_submit = st.form_submit_button("Enviar solicitação")
            if register_submit:
                if register_password != register_confirmation:
                    st.warning("As senhas precisam ser iguais.")
                else:
                    response = chamar_api("POST", "/auth/register", json={
                        "name": register_name, "email": register_email, "password": register_password})
                    if response is not None:
                        if response.status_code == 201:
                            st.success("Solicitação recebida. Aguarde a aprovação do administrador e depois entre pela tela de login.")
                        else:
                            st.error(mensagem_erro(response))
        st.caption("Contas pendentes, rejeitadas ou bloqueadas não acessam o catálogo interno.")
    st.stop()

usuario = st.session_state.usuario
with st.sidebar:
    st.title("📚 Biblioteca")
    st.write(f"Olá, **{usuario['name']}**!")
    st.caption("Perfil: " + ROLE_LABELS[usuario["role"]])
    if st.button("Sair"):
        response = chamar_api("POST", "/auth/logout")
        if response is not None:
            if response.status_code == 200:
                limpar_login()
                st.rerun()
            st.error(mensagem_erro(response))

if "sucesso" in st.session_state:
    st.success(st.session_state.pop("sucesso"))

st.title("Explore nossa biblioteca")
if not usuario.get("member_id"):
    st.info("Sua conta ainda não está associada a um leitor. Para emprestar, peça ao administrador a associação em Contas e leitores.")

nomes = ["Catálogo", "Meus empréstimos"]
if usuario["is_admin"]:
    nomes += ["Administração", "Usuários"]
if usuario["role"] == "attendant":
    nomes += ["Atendimento"]
nomes += ["Minha conta"]
abas = st.tabs(nomes)

with abas[0]:
    busca = st.text_input("Pesquisar", placeholder="Digite o título ou o nome do autor...")
    livros = consultar("/books")
    if livros is not None:
        termo = busca.strip().casefold()
        filtrados = [book for book in livros if termo in book["title"].casefold()
                     or termo in book["author"].casefold()]
        st.caption(f"{len(filtrados)} livro(s) encontrado(s).")
        if not livros:
            st.info("O catálogo ainda não possui livros cadastrados.")
        elif not filtrados:
            st.info("Nenhum livro corresponde à sua pesquisa.")
        colunas = st.columns(3)
        for indice, livro in enumerate(filtrados):
            with colunas[indice % 3]:
                with st.container(border=True):
                    st.subheader(livro["title"])
                    st.write(f"**Autor:** {livro['author']}")
                    st.write(livro.get("description") or "Sem descrição.")
                    st.write(f"Disponíveis: **{livro['available_copies']}** de {livro['total_copies']}")
                    if st.button("Emprestar para mim", key="borrow_" + livro["id"],
                                 disabled=livro["available_copies"] == 0):
                        executar("POST", "/loans", "Empréstimo registrado. O prazo é de 14 dias.",
                                 json={"book_id": livro["id"]})


def mostrar_emprestimos(emprestimos, prefixo, mostrar_leitor=False):
    if emprestimos is None:
        return
    for title, closed in [("Ativos", False), ("Histórico", True)]:
        st.subheader(title)
        items = [loan for loan in emprestimos if bool(loan["returned_at"]) == closed]
        if not items:
            st.caption("Nenhum empréstimo nesta seção.")
        for loan in items:
            with st.container(border=True):
                st.write(f"**{loan['book_title']}** — patrimônio {loan['inventory_code']}")
                if mostrar_leitor:
                    st.write(f"Leitor: {loan['member_name']} ({loan['member_id']})")
                st.write(f"Retirada: {data_local(loan['borrowed_at'])} · Prazo: {data_local(loan['due_at'])}")
                if closed:
                    st.write("Devolvido em: " + data_local(loan["returned_at"]))
                else:
                    if loan["overdue"]:
                        st.warning("Em atraso. Registre a devolução quando devolver o exemplar.")
                    if st.button("Registrar devolução", key=prefixo + loan["id"]):
                        executar("POST", f"/loans/{loan['id']}/return",
                                 "Devolução registrada. O empréstimo permanece no histórico.")


with abas[1]:
    st.caption("Nesta demonstração você pode registrar a devolução dos próprios empréstimos. Horários de Brasília.")
    mostrar_emprestimos(consultar("/loans"), "return_mine_")

if usuario["is_admin"]:
    with abas[2]:
        st.subheader("Cadastros")
        with st.expander("Cadastrar livro"):
            with st.form("book"):
                title = st.text_input("Título")
                author = st.text_input("Autor")
                description = st.text_area("Descrição")
                save_book = st.form_submit_button("Cadastrar livro")
            if save_book:
                executar("POST", "/books", "Livro cadastrado, inicialmente sem exemplares.",
                         json={"title": title, "author": author, "description": description})
        with st.expander("Cadastrar leitor"):
            with st.form("member"):
                name = st.text_input("Nome do leitor")
                email = st.text_input("E-mail do leitor")
                save_member = st.form_submit_button("Cadastrar leitor")
            if save_member:
                executar("POST", "/members", "Leitor cadastrado. Associe uma conta abaixo.",
                         json={"name": name, "email": email})

        st.subheader("Exemplares")
        if livros:
            books_by_id = {book["id"]: book for book in livros}
            selected_book = st.selectbox("Livro do exemplar", list(books_by_id),
                format_func=lambda value: f"{books_by_id[value]['title']} — {books_by_id[value]['author']} ({value})")
            with st.form("copy"):
                code = st.text_input("Código de patrimônio", max_chars=100)
                save_copy = st.form_submit_button("Cadastrar exemplar")
            if save_copy:
                executar("POST", f"/books/{selected_book}/copies", "Exemplar cadastrado.",
                         json={"inventory_code": code})
            copies = consultar(f"/books/{selected_book}/copies")
            if copies:
                st.dataframe(copies, hide_index=True)
            elif copies is not None:
                st.caption("Este livro ainda não possui exemplares.")
        else:
            st.info("Cadastre um livro para adicionar exemplares.")

        st.subheader("Contas e leitores")
        st.caption("Solicitações públicas são aprovadas na aba Usuários. Contas antigas ou criadas pelo CLI podem ser associadas aqui; o vínculo é fixo.")
        users = consultar("/users")
        members = consultar("/members")
        if users is not None and members is not None:
            st.dataframe(users, hide_index=True)
            linked = {user["member_id"] for user in users if user.get("member_id")}
            free_users = {user["id"]: user for user in users if not user.get("member_id")}
            free_members = {member["id"]: member for member in members if member["id"] not in linked}
            if free_users and free_members:
                with st.form("association"):
                    user_id = st.selectbox("Conta de acesso", list(free_users),
                        format_func=lambda value: f"{free_users[value]['name']} — {free_users[value]['email']} ({value})")
                    member_id = st.selectbox("Leitor cadastrado", list(free_members),
                        format_func=lambda value: f"{free_members[value]['name']} — {free_members[value]['email']} ({value})")
                    associate = st.form_submit_button("Associar conta e leitor")
                if associate:
                    executar("PUT", f"/users/{user_id}/member", "Conta e leitor associados.",
                             json={"member_id": member_id})
            else:
                st.info("É necessário ter uma conta e um leitor ainda sem vínculo para fazer uma associação.")

        st.subheader("Todos os empréstimos")
        mostrar_emprestimos(consultar("/loans?scope=all"), "return_admin_", mostrar_leitor=True)

# Gestão de acesso fica separada do acervo.
if usuario["role"] == "admin":
    with abas[nomes.index("Usuários")]:
        st.subheader("Solicitações e acesso")
        st.caption("Somente administradores aprovam contas e atribuem papéis. Alterações de acesso encerram as sessões antigas da conta.")
        users = consultar("/users")
        members = consultar("/members")
        if users is not None and members is not None:
            status_labels = {"pending": "Pendente", "approved": "Aprovada",
                             "rejected": "Rejeitada", "blocked": "Bloqueada"}
            filter_status = st.selectbox("Filtrar situação", ["all", *status_labels],
                format_func=lambda value: "Todas" if value == "all" else status_labels[value])
            targets = {user["id"]: user for user in users
                       if filter_status == "all" or user["status"] == filter_status}
            st.dataframe([{**user, "role": ROLE_LABELS[user["role"]],
                           "status": status_labels[user["status"]]} for user in targets.values()],
                         hide_index=True)
            if targets:
                selected = st.selectbox("Conta para gerenciar", list(targets),
                    format_func=lambda value: f"{targets[value]['name']} — {targets[value]['email']} ({value})")
                target = targets[selected]
                st.write(f"Situação: **{status_labels[target['status']]}** · Papel: **{ROLE_LABELS[target['role']]}**")
                if selected == usuario["id"]:
                    st.info("Sua própria conta não pode ser bloqueada nem ter o papel alterado por você.")
                elif target["status"] in ("pending", "rejected", "blocked"):
                    linked = {user["member_id"] for user in users if user.get("member_id")}
                    free_members = {member["id"]: member for member in members if member["id"] not in linked}
                    approval_data = {}
                    if target.get("member_id"):
                        st.info("A aprovação preservará o leitor já associado.")
                    else:
                        choice = st.radio("Vínculo na aprovação", ["Criar novo leitor", "Associar leitor existente"],
                                          key="link_choice_" + selected)
                        if choice == "Criar novo leitor":
                            st.caption("Cria um leitor com o nome e o e-mail desta conta. Se o e-mail já existir entre os leitores, escolha explicitamente o cadastro correto.")
                            approval_data = {"create_member": True}
                        elif free_members:
                            member_id = st.selectbox("Leitor para aprovação", list(free_members),
                                format_func=lambda value: f"{free_members[value]['name']} — {free_members[value]['email']} ({value})",
                                key="approve_member_" + selected)
                            approval_data = {"member_id": member_id}
                        else:
                            st.warning("Não há leitores livres para associar.")
                    with st.form("approve_" + selected):
                        confirmed = st.checkbox("Conferi a identidade e confirmo a aprovação")
                        approve = st.form_submit_button("Aprovar conta")
                    if approve:
                        if not confirmed:
                            st.warning("Confirme a identidade e a aprovação antes de continuar.")
                        elif not target.get("member_id") and not approval_data:
                            st.warning("Escolha um leitor para a associação.")
                        else:
                            executar("POST", f"/users/{selected}/approve", "Conta aprovada. O usuário já pode entrar.",
                                     json=approval_data)
                    if target["status"] == "pending":
                        with st.form("reject_" + selected):
                            confirmed_reject = st.checkbox("Confirmo a rejeição desta solicitação")
                            reject = st.form_submit_button("Rejeitar cadastro")
                        if reject:
                            if confirmed_reject:
                                executar("POST", f"/users/{selected}/reject", "Cadastro rejeitado.")
                            else:
                                st.warning("Confirme a rejeição antes de continuar.")
                else:
                    with st.form("role_" + selected):
                        role = st.selectbox("Novo papel", list(ROLE_LABELS),
                                            index=list(ROLE_LABELS).index(target["role"]),
                                            format_func=lambda value: ROLE_LABELS[value])
                        confirmed_role = st.checkbox("Confirmo a alteração de papel")
                        change_role = st.form_submit_button("Alterar papel")
                    if change_role:
                        if confirmed_role:
                            executar("PUT", f"/users/{selected}/role", "Papel atualizado. A conta deve entrar novamente.",
                                     json={"role": role})
                        else:
                            st.warning("Confirme a alteração de papel antes de continuar.")
                    with st.form("block_" + selected):
                        confirmed_block = st.checkbox("Confirmo o bloqueio desta conta")
                        block = st.form_submit_button("Bloquear conta")
                    if block:
                        if confirmed_block:
                            executar("POST", f"/users/{selected}/block", "Conta bloqueada. Seus registros foram preservados.")
                        else:
                            st.warning("Confirme o bloqueio antes de continuar.")
            else:
                st.info("Nenhuma conta nesta situação.")

if usuario["role"] == "attendant":
    with abas[nomes.index("Atendimento")]:
        st.subheader("Atendimento de empréstimos")
        st.info("Etapa A: consulta e devolução dos empréstimos existentes. Solicitações e confirmação de entrega física serão implementadas na etapa B.")
        mostrar_emprestimos(consultar("/loans?scope=all"), "return_staff_", mostrar_leitor=True)

with abas[nomes.index("Minha conta")]:
    st.subheader("Minha conta")
    st.write(f"Nome: {usuario['name']}")
    st.write(f"E-mail: {usuario['email']}")
    st.write(f"Papel: {ROLE_LABELS[usuario['role']]}")
    st.write("Situação: aprovada")
    st.write("Leitor associado: " + (usuario.get("member_id") or "Ainda sem vínculo"))
