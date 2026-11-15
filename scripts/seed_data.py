import asyncio
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.core.database import Base, async_session_maker, engine
from app.core.security import hash_password, hash_secret_key
from app.models.common import FAQEntry
from app.models.course import Course, Document, DocumentChunk
from app.models.job import Job
from app.models.platform import Platform, PlatformConfiguration, PlatformDomain
from app.models.user import User, UserPhone, UserPlatformMembership
from app.services.ai.embeddings import get_embedding


async def seed():
    print("🌱 Initializing database schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        # Check if already seeded
        res = await session.execute(
            select(Platform).where(Platform.domain == "savanna.example.com")
        )
        existing_platform = res.scalar_one_or_none()
        if existing_platform:
            # Ensure Savanna Platform Admin exists
            adm_res = await session.execute(
                select(User).where(User.email == "admin@savanna.alx")
            )
            if not adm_res.scalar_one_or_none():
                savanna_admin = User(
                    email="admin@savanna.alx",
                    full_name="Savanna Platform Admin",
                    role="platform_admin",
                    status="approved",
                    assigned_platform_id=existing_platform.id,
                    hashed_password=hash_password("SavannaAdmin123!"),
                    is_active=True,
                )
                session.add(savanna_admin)
                await session.flush()
                session.add(
                    UserPlatformMembership(
                        user_id=savanna_admin.id,
                        platform_id=existing_platform.id,
                        external_learner_id="SAVANNA_ADM_001",
                        role="admin",
                    )
                )
                await session.commit()
                print("✅ Seeded Savanna Platform Admin: admin@savanna.alx")
            print("✅ Database already contains seed data.")
            return

        print("🚀 Seeding Platform: Savanna LMS...")
        savanna_platform = Platform(
            name="Savanna",
            domain="savanna.example.com",
            public_key="pk_live_savanna_sample_12345",
            secret_key_hash=hash_secret_key("sk_live_savanna_secret_67890"),
            enabled=True,
        )
        session.add(savanna_platform)
        await session.flush()

        # Add domain entries
        session.add(
            PlatformDomain(
                platform_id=savanna_platform.id, domain="savanna.example.com", is_verified=True
            )
        )
        session.add(
            PlatformDomain(
                platform_id=savanna_platform.id, domain="localhost:3000", is_verified=True
            )
        )
        session.add(
            PlatformDomain(
                platform_id=savanna_platform.id, domain="localhost:5173", is_verified=True
            )
        )
        session.add(
            PlatformDomain(
                platform_id=savanna_platform.id, domain="vercel.app", is_verified=True
            )
        )
        session.add(
            PlatformDomain(
                platform_id=savanna_platform.id, domain="savana-three.vercel.app", is_verified=True
            )
        )
        session.add(
            PlatformDomain(
                platform_id=savanna_platform.id, domain="meri-plugin.vercel.app", is_verified=True
            )
        )

        # Add configuration matching Frontend Specification Section 4
        config = PlatformConfiguration(
            platform_id=savanna_platform.id,
            platform_name="Savanna",
            theme={
                "primary": "#16A34A",
                "secondary": "#14532D",
                "background": "#FFFFFF",
                "text": "#111827",
                "chat_button": "#16A34A",
            },
            branding={"logo_url": "https://example.com/logo.png"},
            welcome_message="Welcome to Savanna! How can I assist your studies or career today?",
            language="en",
            position="bottom-right",
            size="medium",
            features={
                "voice": True,
                "human_support": True,
                "simple_mode": True,
                "job_assistance": True,
                "course_assistant": True,
            },
        )
        session.add(config)

        # Users
        print("👤 Seeding Users (Admin & Verified Learner)...")
        admin = User(
            email="admin@bridgemate.internal",
            full_name="System SuperAdmin",
            role="superadmin",
            status="approved",
            hashed_password=hash_password("AdminPass123!"),
            is_active=True,
        )
        session.add(admin)

        savanna_admin = User(
            email="admin@savanna.alx",
            full_name="Savanna Platform Admin",
            role="platform_admin",
            status="approved",
            assigned_platform_id=savanna_platform.id,
            hashed_password=hash_password("SavannaAdmin123!"),
            is_active=True,
        )
        session.add(savanna_admin)

        learner = User(
            email="learner@savanna.example.com",
            full_name="Dawit Bekele",
            role="learner",
            hashed_password=hash_password("StudentPass123!"),
            is_active=True,
        )
        session.add(learner)
        await session.flush()

        session.add(
            UserPlatformMembership(
                user_id=savanna_admin.id,
                platform_id=savanna_platform.id,
                external_learner_id="SAVANNA_ADM_001",
                role="admin",
            )
        )

        # Add verified phone for Telegram linking
        learner_phone = UserPhone(
            user_id=learner.id,
            phone_number="+251911223344",
            is_verified=True,
        )
        session.add(learner_phone)

        # Add platform membership
        membership = UserPlatformMembership(
            user_id=learner.id,
            platform_id=savanna_platform.id,
            external_learner_id="SAVANNA_STU_001",
            role="learner",
        )
        session.add(membership)

        # Courses & Knowledge Material
        print("📚 Seeding Course and Knowledge Base Chunks...")
        course = Course(
            platform_id=savanna_platform.id,
            course_code="CS101",
            title="Introduction to Python and Web Development",
            description="Foundations of programming in Python, algorithms, data structures, and web APIs.",
            instructor_name="Dr. Abebe Bekele",
            is_active=True,
        )
        session.add(course)
        await session.flush()

        doc = Document(
            course_id=course.id,
            platform_id=savanna_platform.id,
            title="Python Fundamentals and Data Structures",
            file_type="txt",
            file_path="python_fundamentals.txt",
            file_size=2048,
            is_processed=True,
            chunk_count=2,
        )
        session.add(doc)
        await session.flush()

        chunk_texts = [
            (
                "Python variables and data types: Python supports integers, floats, strings, and booleans. "
                "Lists in Python are ordered and mutable sequences. Dictionaries store key-value mappings. "
                "Functions are defined using the 'def' keyword and can return values.",
                1,
                "Variables and Data Types",
            ),
            (
                "Object-Oriented Programming in Python: Classes are blueprints for creating objects. "
                "The '__init__' method initializes class instances. "
                "Inheritance allows a child class to inherit attributes and methods from a parent class.",
                2,
                "Classes and Inheritance",
            ),
        ]

        for idx, (text, page, sec) in enumerate(chunk_texts):
            emb = await get_embedding(text)
            chunk = DocumentChunk(
                document_id=doc.id,
                course_id=course.id,
                platform_id=savanna_platform.id,
                chunk_index=idx,
                content=text,
                page_number=page,
                section_title=sec,
                embedding=emb,
                metadata_json={"course_code": "CS101", "lesson": sec},
            )
            session.add(chunk)

        # Jobs
        print("💼 Seeding Career Opportunities...")
        job1 = Job(
            platform_id=savanna_platform.id,
            title="Junior Python Developer",
            company="Savanna Tech Hub",
            location="Addis Ababa",
            description="We are seeking an ambitious Junior Python Developer to build and maintain REST APIs using FastAPI and Django.",
            requirements=[
                "Python 3.x proficiency",
                "Basic knowledge of relational databases (PostgreSQL)",
                "Understanding of RESTful APIs",
                "Familiarity with Git",
            ],
            skills=["Python", "Django", "FastAPI", "PostgreSQL", "REST APIs", "Git"],
            application_instructions="Apply with your GitHub portfolio and CV through the platform career tab.",
            job_url="/jobs/junior-python-developer",
            is_active=True,
        )
        job2 = Job(
            platform_id=savanna_platform.id,
            title="Frontend React Specialist",
            company="AfroTech Solutions",
            location="Remote",
            description="Join our frontend engineering team to craft accessible and responsive web plugins with React and TypeScript.",
            requirements=[
                "2+ years React experience",
                "Solid TypeScript background",
                "CSS/Tailwind experience",
                "Understanding of WebSockets",
            ],
            skills=["React", "TypeScript", "Tailwind CSS", "WebSockets"],
            application_instructions="Submit your portfolio demonstrating custom components.",
            job_url="/jobs/frontend-react-specialist",
            is_active=True,
        )
        session.add(job1)
        session.add(job2)

        # FAQs
        print("💡 Seeding Approved FAQs...")
        faq1 = FAQEntry(
            platform_id=savanna_platform.id,
            category="job",
            question="How do I prepare for a technical interview?",
            answer="Review your core technical skills, practice explaining code logic out loud, use the STAR format for behavioral questions, and practice mock questions.",
            language="en",
            keywords=["interview", "prepare", "practice", "questions"],
            is_approved=True,
        )
        faq2 = FAQEntry(
            platform_id=savanna_platform.id,
            category="accessibility",
            question="How can I request interview accommodations?",
            answer="You can submit a confidential accommodation request through the BridgeMate assistant. The request will be shared with the recruiter only with your consent.",
            language="en",
            keywords=["accommodation", "accessibility", "disability"],
            is_approved=True,
        )
        session.add(faq1)
        session.add(faq2)

        await session.commit()
        print("🎉 Seeding completed successfully!")
        print("--------------------------------------------------")
        print("Platform: Savanna")
        print("Public Key: pk_live_savanna_sample_12345")
        print("Secret Key: sk_live_savanna_secret_67890")
        print("Learner Email: learner@savanna.example.com")
        print("Learner Phone: +251911223344")
        print("Admin Email: admin@bridgemate.internal / AdminPass123!")
        print("--------------------------------------------------")


if __name__ == "__main__":
    asyncio.run(seed())
