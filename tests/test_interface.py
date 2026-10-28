"""Executa a tela Streamlit com a API Flask real, sem abrir portas de rede."""
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

import requests
from streamlit.testing.v1 import AppTest

from test_current import DatabaseCase, app, db
from models import User


class FlaskSession:
    def __init__(self):
        self.client = app.test_client()

    def request(self, method, url, timeout=None, **kwargs):
        parts = urlsplit(url)
        path = parts.path + ("?" + parts.query if parts.query else "")
        result = self.client.open(path, method=method, **kwargs)
        response = requests.Response()
        response.status_code = result.status_code
        response._content = result.data
        response.headers.update(result.headers)
        return response

    def close(self):
        pass


class InterfaceTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.sessions = []
        def factory():
            session = FlaskSession()
            self.sessions.append(session)
            return session
        self.mock = patch("requests.Session", side_effect=factory)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def screen(self):
        return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "interface.py"), default_timeout=20).run()

    def input(self, screen, label, value):
        next(item for item in screen.text_input if item.label == label).set_value(value)

    def click(self, screen, label):
        next(item for item in screen.button if item.label == label).click().run()
        self.assertEqual(len(screen.exception), 0)

    def enter(self, screen, name):
        self.input(screen, "E-mail", name + "@example.test")
        self.input(screen, "Senha", "senha-de-teste")
        self.click(screen, "Entrar")

    def test_admin_forms_and_reader_lifecycle(self):
        screen = self.screen()
        self.enter(screen, "admin")
        self.input(screen, "Título", "Livro da interface")
        self.input(screen, "Autor", "Autora")
        self.click(screen, "Cadastrar livro")
        self.assertTrue(any(button.disabled for button in screen.button if button.label == "Emprestar para mim"))
        self.input(screen, "Código de patrimônio", "TELA-001")
        self.click(screen, "Cadastrar exemplar")
        self.input(screen, "Nome do leitor", "Ana leitora")
        self.input(screen, "E-mail do leitor", "ana@example.test")
        self.click(screen, "Cadastrar leitor")
        user = db.session.scalar(db.select(User).where(User.name == "ana"))
        next(item for item in screen.selectbox if item.label == "Conta de acesso").set_value(str(user.id))
        self.click(screen, "Associar conta e leitor")
        self.click(screen, "Sair")
        self.enter(screen, "ana")
        self.assertEqual([tab.label for tab in screen.tabs], ["Catálogo", "Meus empréstimos", "Minha conta"])
        self.input(screen, "Pesquisar", "não existe")
        screen.run()
        self.assertFalse(any(button.label == "Emprestar para mim" for button in screen.button))
        self.input(screen, "Pesquisar", "Autora")
        screen.run()
        self.click(screen, "Emprestar para mim")
        self.assertTrue(any(button.label == "Registrar devolução" for button in screen.button))
        self.click(screen, "Registrar devolução")
        self.assertFalse(any(button.label == "Registrar devolução" for button in screen.button))
        self.assertTrue(any("Devolvido em:" in item.value for item in screen.markdown))
        self.assertEqual(len(screen.exception), 0)

    def test_separate_sessions_and_expiration(self):
        first, second = self.screen(), self.screen()
        self.enter(first, "ana")
        self.enter(second, "bia")
        self.assertNotEqual(self.sessions[0], self.sessions[1])
        self.assertTrue(any("ana" in item.value for item in first.sidebar.markdown))
        self.assertTrue(any("bia" in item.value for item in second.sidebar.markdown))
        self.assertTrue(any("associada" in item.value for item in first.info))
        with self.sessions[0].client.session_transaction() as session:
            session.clear()
        first.run()
        self.assertTrue(any("sessão terminou" in item.value for item in first.warning))
        self.assertTrue(any(button.label == "Entrar" for button in first.button))
        second.run()
        self.assertTrue(any("bia" in item.value for item in second.sidebar.markdown))
        self.assertEqual(len(first.exception) + len(second.exception), 0)

    def select_target(self, screen, user_id):
        next(item for item in screen.selectbox if item.label == "Conta para gerenciar").set_value(str(user_id))
        screen.run()
        self.assertEqual(len(screen.exception), 0)

    def confirm(self, screen, label):
        next(item for item in screen.checkbox if item.label == label).check()

    def test_public_form_preserves_errors_and_pending_cannot_enter(self):
        screen = self.screen()
        self.input(screen, "Nome completo", "Nova")
        self.input(screen, "E-mail do cadastro", "invalido")
        self.input(screen, "Senha do cadastro", "senha-de-teste")
        self.input(screen, "Confirme a senha", "senha-de-teste")
        self.click(screen, "Enviar solicitação")
        self.assertTrue(any("e-mail" in error.value for error in screen.error))
        self.assertEqual(next(item for item in screen.text_input if item.label == "Nome completo").value, "Nova")
        self.input(screen, "E-mail do cadastro", "nova@example.test")
        self.click(screen, "Enviar solicitação")
        self.assertTrue(any("Aguarde" in item.value for item in screen.success))
        self.enter(screen, "nova")
        self.assertTrue(any("pendente" in item.value for item in screen.error))
        self.assertEqual(len(screen.tabs), 0)

    def test_admin_approval_role_block_and_attendant_screen(self):
        self.client.post("/auth/register", json={
            "name": "Nova", "email": "nova@example.test", "password": "senha-de-teste"})
        user = db.session.scalar(db.select(User).where(User.email == "nova@example.test"))
        identifier = str(user.id)
        screen = self.screen()
        self.enter(screen, "admin")
        self.select_target(screen, identifier)
        self.click(screen, "Aprovar conta")
        db.session.expire_all()
        self.assertEqual(user.status, "pending")
        self.confirm(screen, "Conferi a identidade e confirmo a aprovação")
        self.click(screen, "Aprovar conta")
        db.session.expire_all()
        self.assertEqual(user.status, "approved")
        self.assertIsNotNone(user.member_id)
        next(item for item in screen.selectbox if item.label == "Novo papel").set_value("attendant")
        self.confirm(screen, "Confirmo a alteração de papel")
        self.click(screen, "Alterar papel")
        attendant = self.screen()
        self.enter(attendant, "nova")
        self.assertIn("Atendimento", [tab.label for tab in attendant.tabs])
        self.assertNotIn("Usuários", [tab.label for tab in attendant.tabs])
        self.confirm(screen, "Confirmo o bloqueio desta conta")
        self.click(screen, "Bloquear conta")
        attendant.run()
        self.assertTrue(any("sessão terminou" in item.value for item in attendant.warning))
        self.assertEqual(len(attendant.tabs), 0)
        self.confirm(screen, "Conferi a identidade e confirmo a aprovação")
        self.click(screen, "Aprovar conta")
        self.enter(attendant, "nova")
        self.assertIn("Atendimento", [tab.label for tab in attendant.tabs])

    def test_admin_rejection_and_explicit_member_approval(self):
        self.login()
        member = self.client.post("/members", json={"name": "Existente", "email": "novo@example.test"}).get_json()
        self.client.post("/auth/register", json={
            "name": "Novo", "email": "novo@example.test", "password": "senha-de-teste"})
        user = db.session.scalar(db.select(User).where(User.email == "novo@example.test"))
        screen = self.screen()
        self.enter(screen, "admin")
        self.select_target(screen, user.id)
        self.confirm(screen, "Confirmo a rejeição desta solicitação")
        self.click(screen, "Rejeitar cadastro")
        db.session.expire_all()
        self.assertEqual(user.status, "rejected")
        next(item for item in screen.radio if item.label == "Vínculo na aprovação").set_value("Associar leitor existente")
        screen.run()
        next(item for item in screen.selectbox if item.label == "Leitor para aprovação").set_value(member["id"])
        self.confirm(screen, "Conferi a identidade e confirmo a aprovação")
        self.click(screen, "Aprovar conta")
        db.session.expire_all()
        self.assertEqual(user.status, "approved")
        self.assertEqual(str(user.member_id), member["id"])
