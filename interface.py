import requests
import streamlit as st

API_URL = "http://127.0.0.1:5000"

st.set_page_config(
    page_title="Minha Biblioteca",
    page_icon="📚",
    layout="wide"
)


# Cada sessão da interface mantém seus próprios cookies de login.
if "api" not in st.session_state:
    st.session_state.api = requests.Session()


def chamar_api(metodo, rota, **kwargs):
    try:
        return st.session_state.api.request(
            metodo,
            f"{API_URL}{rota}",
            timeout=10,
            **kwargs
        )
    except requests.RequestException:
        st.error(
            "Não foi possível acessar a API. "
            "Confira se o Flask está rodando na porta 5000."
        )
        return None


def mensagem_erro(resposta):
    try:
        return resposta.json().get("erro", "Não foi possível concluir.")
    except ValueError:
        return "O servidor retornou uma resposta inesperada."


def limpar_login():
    st.session_state.api.cookies.clear()
    st.session_state.pop("usuario", None)


# Confere a sessão no Flask antes de mostrar a área interna.
if "usuario" in st.session_state:
    resposta = chamar_api("GET", "/auth/me")

    if resposta is None:
        st.stop()

    if resposta.status_code == 200:
        st.session_state.usuario = resposta.json()
    elif resposta.status_code == 401:
        limpar_login()
        st.warning("Sua sessão terminou. Entre novamente.")
    else:
        st.error(mensagem_erro(resposta))
        st.stop()


# Tela de login.
if "usuario" not in st.session_state:
    esquerda, centro, direita = st.columns([1, 2, 1])

    with centro:
        st.title("📚 Minha Biblioteca")
        st.write("Entre na sua conta para explorar o catálogo.")

        with st.form("login"):
            email = st.text_input("E-mail")
            senha = st.text_input("Senha", type="password")
            entrar = st.form_submit_button(
                "Entrar",
                use_container_width=True
            )

        if entrar:
            if not email.strip() or not senha:
                st.warning("Preencha o e-mail e a senha.")
            else:
                resposta = chamar_api(
                    "POST",
                    "/auth/login",
                    json={
                        "email": email.strip(),
                        "password": senha
                    }
                )

                if resposta is not None:
                    if resposta.status_code == 200:
                        st.session_state.usuario = resposta.json()["user"]
                        st.rerun()
                    else:
                        st.error(mensagem_erro(resposta))

        st.caption(
            "Ainda não tem acesso? Solicite uma conta ao administrador."
        )

    st.stop()


# Área interna.
usuario = st.session_state.usuario

with st.sidebar:
    st.title("📚 Biblioteca")
    st.write(f"Olá, **{usuario['name']}**!")

    perfil = "Administrador" if usuario["is_admin"] else "Leitor"
    st.caption(f"Perfil: {perfil}")

    st.divider()
    st.write("Catálogo de livros")

    if st.button("Sair", use_container_width=True):
        resposta = chamar_api("POST", "/auth/logout")

        if resposta is not None:
            if resposta.status_code in (200, 401):
                limpar_login()
                st.rerun()
            else:
                st.error(mensagem_erro(resposta))


st.title("Explore nossa biblioteca")
st.write("Encontre sua próxima leitura pelo título ou pelo autor.")

busca = st.text_input(
    "Pesquisar",
    placeholder="Digite o título ou o nome do autor..."
)

resposta = chamar_api("GET", "/books")

if resposta is None:
    st.stop()

if resposta.status_code == 401:
    limpar_login()
    st.rerun()

if resposta.status_code != 200:
    st.error(mensagem_erro(resposta))
    st.stop()

livros = resposta.json()
termo = busca.strip().casefold()

filtrados = [
    livro
    for livro in livros
    if termo in livro["title"].casefold()
    or termo in livro["author"].casefold()
]

st.caption(f"{len(filtrados)} livro(s) encontrado(s).")

if not livros:
    st.info("O catálogo ainda não possui livros cadastrados.")
elif not filtrados:
    st.info("Nenhum livro corresponde à sua pesquisa.")
else:
    colunas = st.columns(3)

    for indice, livro in enumerate(filtrados):
        with colunas[indice % 3]:
            with st.container(border=True):
                st.subheader(livro["title"])
                st.write(f"**Autor:** {livro['author']}")
                st.write(
                    livro.get("description") or "Sem descrição."
                )