import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_and_root():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

        root_resp = await ac.get("/")
        assert root_resp.status_code == 200
        assert root_resp.json()["status"] == "operational"


@pytest.mark.asyncio
async def test_plugin_config_retrieval():
    """Matches Frontend Specification Section 3 & 4."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/plugin/config/pk_live_savanna_sample_12345")
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform_name"] == "Savanna"
        assert data["theme"]["primary"].startswith("#")
        assert data["theme"]["background"].upper() == "#FFFFFF"
        assert data["features"]["voice"] is True
        assert data["features"]["human_support"] is True
        assert data["position"] == "bottom-right"


@pytest.mark.asyncio
async def test_dynamic_plugin_config_update():
    """Verify changes in platform configuration apply dynamically without frontend rebuild."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        unique_domain = f"test-{uuid.uuid4().hex[:8]}.example.com"

        # Register platform
        reg_resp = await ac.post(
            "/api/v1/platforms",
            json={
                "name": "Dynamic Platform",
                "domain": unique_domain,
                "allowed_domains": [unique_domain],
            },
        )
        assert reg_resp.status_code == 201
        plat_data = reg_resp.json()
        plat_id = plat_data["id"]
        pub_key = plat_data["public_key"]

        # 2. Update colors dynamically
        patch_resp = await ac.patch(
            f"/api/v1/platforms/{plat_id}/plugin-config",
            json={
                "platform_name": "Updated Dynamic Platform",
                "theme": {
                    "primary": "#2563EB",
                    "secondary": "#1E40AF",
                    "background": "#F8FAFC",
                    "text": "#0F172A",
                    "chat_button": "#2563EB",
                },
            },
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["theme"]["primary"] == "#2563EB"

        # 3. Verify public plugin config endpoint returns new colors immediately without rebuild
        live_cfg = await ac.get(f"/api/v1/plugin/config/{pub_key}")
        assert live_cfg.status_code == 200
        assert live_cfg.json()["theme"]["primary"] == "#2563EB"
        assert live_cfg.json()["platform_name"] == "Updated Dynamic Platform"


@pytest.mark.asyncio
async def test_context_sanitization_and_analysis():
    """Frontend Specification Section 5 & Backend Specification Section 6."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Context with sensitive password & token
        payload = {
            "context": {
                "page_type": "job",
                "url": "https://savanna.example.com/jobs/junior-python-developer",
                "title": "Junior Python Developer",
                "content": {
                    "company": "Savanna Tech Hub",
                    "description": "Develop web applications.",
                    "requirements": ["Python", "Django", "React"],
                    "skills": ["Python", "FastAPI"],
                    "password_field": "SuperSecretPassword123!",
                },
            }
        }
        resp = await ac.post("/api/v1/context/validate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_valid"] is True
        assert data["page_type"] == "job"
        assert "password_field" not in data["sanitized_content"]

        # Analyze context
        analyze_resp = await ac.post("/api/v1/context/analyze", json=payload)
        assert analyze_resp.status_code == 200
        a_data = analyze_resp.json()
        assert a_data["page_type"] == "job"
        assert len(a_data["suggested_quick_actions"]) > 0
        assert "Am I qualified for this position?" in a_data["suggested_quick_actions"]


@pytest.mark.asyncio
async def test_server_to_server_learner_auth():
    """Backend Specification Section 5.1: Host server requests short-lived BridgeMate token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "public_key": "pk_live_savanna_sample_12345",
            "secret_key": "sk_live_savanna_secret_67890",
            "external_learner_id": "SAVANNA_STU_001",
            "learner_name": "Dawit Bekele",
            "learner_email": "learner@savanna.example.com",
            "role": "learner",
        }
        resp = await ac.post("/api/v1/auth/token", json=payload)
        assert resp.status_code == 200
        token_data = resp.json()
        assert "access_token" in token_data
        assert token_data["token_type"] == "bearer"

        # Verify access to /auth/me with bearer token
        headers = {"Authorization": f"Bearer {token_data['access_token']}"}
        me_resp = await ac.get("/api/v1/auth/me", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["full_name"] == "Dawit Bekele"


@pytest.mark.asyncio
async def test_course_chat_with_grounded_citations():
    """Course question generates answer with institution citations."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {
            "message": "What data types does Python support according to our lesson?",
            "context": {
                "page_type": "lesson",
                "url": "/courses/cs101/lesson-1",
                "title": "Variables and Data Types",
                "content": "Lesson 1: Introduction to Variables and Python Types",
            },
            "language": "en",
        }
        headers = {"X-Public-Key": "pk_live_savanna_sample_12345"}
        resp = await ac.post("/api/v1/chat/messages", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert len(data["response"]) > 0
        assert data["provider_used"] in ["gemini", "groq", "offline_faq"]
        assert len(data["suggested_actions"]) > 0


@pytest.mark.asyncio
async def test_job_chat_and_career_gateway():
    """Job questions and accommodation requests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        headers = {"X-Public-Key": "pk_live_savanna_sample_12345"}

        # 1. List jobs
        jobs_resp = await ac.get("/api/v1/jobs", headers=headers)
        assert jobs_resp.status_code == 200
        jobs = jobs_resp.json()
        assert len(jobs) > 0
        job_id = jobs[0]["id"]

        # 2. Chat with job context
        chat_payload = {
            "message": "Am I qualified for this junior python position? I know Python and basic Git.",
            "context": {
                "page_type": "job",
                "url": "/jobs/junior-python-developer",
                "title": "Junior Python Developer",
                "job_id": job_id,
                "content": {
                    "company": "Savanna Tech Hub",
                    "requirements": ["Python", "PostgreSQL", "Git"],
                },
            },
            "language": "en",
        }
        chat_resp = await ac.post("/api/v1/chat/messages", json=chat_payload, headers=headers)
        assert chat_resp.status_code == 200
        assert "response" in chat_resp.json()

        # 3. Mint learner token for accommodation request
        token_resp = await ac.post(
            "/api/v1/auth/token",
            json={
                "public_key": "pk_live_savanna_sample_12345",
                "secret_key": "sk_live_savanna_secret_67890",
                "external_learner_id": "SAVANNA_STU_001",
                "learner_name": "Dawit Bekele",
                "role": "learner",
            },
        )
        token = token_resp.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # 4. Submit interview accommodation request
        accom_resp = await ac.post(
            "/api/v1/jobs/accommodations",
            json={
                "job_id": job_id,
                "details": "Screen reader accessible IDE and extended time for coding test.",
                "consent_given": True,
            },
            headers=auth_headers,
        )
        assert accom_resp.status_code == 200
        assert accom_resp.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_human_support_ticket_workflow():
    """Human support request and messaging thread."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        headers = {"X-Public-Key": "pk_live_savanna_sample_12345"}
        ticket_payload = {
            "subject": "Need help with Python Assignment 2",
            "initial_message": "Hello, I am having trouble understanding recursion.",
            "consent_share_history": True,
            "screen_sharing_active": False,
        }
        resp = await ac.post("/api/v1/support/tickets", json=ticket_payload, headers=headers)
        assert resp.status_code == 201
        ticket = resp.json()
        assert ticket["subject"] == "Need help with Python Assignment 2"
        assert ticket["status"] == "open"
        ticket_id = ticket["id"]

        # Post reply message
        msg_resp = await ac.post(
            f"/api/v1/support/tickets/{ticket_id}/messages",
            json={"content": "Can we schedule a 10 minute screen share review?"},
            headers=headers,
        )
        assert msg_resp.status_code == 200
        assert msg_resp.json()["content"] == "Can we schedule a 10 minute screen share review?"


@pytest.mark.asyncio
async def test_telegram_phone_verification_flow():
    """Verified phone contact matching with student records."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        verify_payload = {
            "telegram_chat_id": "987654321",
            "telegram_user_id": "987654321",
            "phone_number": "+251911223344",
            "first_name": "Dawit",
        }
        resp = await ac.post("/api/v1/auth/telegram/verify", json=verify_payload)
        assert resp.status_code == 200
        assert "completed" in resp.json()["status"]

        # Check platforms
        plat_resp = await ac.get("/api/v1/auth/telegram/platforms?telegram_chat_id=987654321")
        assert plat_resp.status_code == 200
        platforms = plat_resp.json()
        assert len(platforms) > 0
        assert platforms[0]["platform_name"] == "Savanna"


@pytest.mark.asyncio
async def test_platform_admin_and_management_endpoints():
    """Verify listing platforms, domain management, status toggling, and key rotation."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. List platforms
        list_resp = await ac.get("/api/v1/platforms")
        assert list_resp.status_code == 200
        platforms = list_resp.json()
        assert len(platforms) > 0
        platform_id = platforms[0]["id"]

        # 2. Add domain
        add_dom = await ac.post(f"/api/v1/platforms/{platform_id}/domains", json={"domain": "learn.test.com"})
        assert add_dom.status_code == 200
        assert add_dom.json()["status"] == "ok"

        # 3. Rotate integration keys
        rotate_resp = await ac.post(f"/api/v1/platforms/{platform_id}/rotate-keys")
        assert rotate_resp.status_code == 200
        rot_data = rotate_resp.json()
        assert "secret_key" in rot_data
        assert rot_data["secret_key"].startswith("sk_live_")

        # 4. Toggle platform status
        status_resp = await ac.patch(f"/api/v1/platforms/{platform_id}/status", json={"enabled": True})
        assert status_resp.status_code == 200
        assert status_resp.json()["enabled"] is True


@pytest.mark.asyncio
async def test_faqs_and_learner_listing():
    """Verify FAQ creation, listing, deletion, and admin learner listing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Create FAQ
        faq_payload = {
            "category": "accessibility",
            "question": "Does BridgeMate support screen readers?",
            "answer": "Yes, BridgeMate provides AAA contrast, keyboard shortcuts, and live screen reader regions.",
            "language": "en",
            "keywords": ["screen reader", "accessibility", "a11y"],
            "is_approved": True,
        }
        create_resp = await ac.post("/api/v1/knowledge/faqs", json=faq_payload)
        assert create_resp.status_code == 201
        faq_data = create_resp.json()
        faq_id = faq_data["id"]

        # 2. List FAQs
        faq_list = await ac.get("/api/v1/knowledge/faqs?category=accessibility")
        assert faq_list.status_code == 200
        assert any(f["id"] == faq_id for f in faq_list.json())

        # 3. List learners
        learners_resp = await ac.get("/api/v1/auth/learners")
        assert learners_resp.status_code == 200
        learners = learners_resp.json()
        assert len(learners) > 0
        assert any(l["phone_number"] == "+251911223344" for l in learners)

        # 4. Cleanup FAQ
        del_resp = await ac.delete(f"/api/v1/knowledge/faqs/{faq_id}")
        assert del_resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_hub_and_static_assets():
    """Verify admin hub HTML and static meri.js bundle are accessible."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        admin_resp = await ac.get("/admin/")
        assert admin_resp.status_code == 200
        assert "Platform" in admin_resp.text

        dashboard_resp = await ac.get("/dashboard/")
        assert dashboard_resp.status_code == 200

        static_bundle = await ac.get("/static/meri.js")
        assert static_bundle.status_code == 200
        assert len(static_bundle.content) > 1000


