"""
Job Description registry — the single source of truth for all JD data.
Structured fields power the match scorer. Full text powers the chatbot prompt.
"""

JDS = {
    "java-architect": {
        "id": "java-architect",
        "title": "Java Architect",
        "location": "Pune / Mumbai",
        "mode": "Hybrid",
        "experience": "12+ years",
        "experience_min": 12,
        "experience_max": 25,
        "department": "Product Engineering",
        "must_have": [
            "Core Java",
            "Java 8+",
            "Spring",
            "Spring Boot",
            "Microservices",
            "REST APIs",
            "Hibernate / JPA",
            "SQL databases",
            "NoSQL databases",
            "Docker",
            "Kubernetes",
            "AWS / Azure / GCP (any one)"
        ],
        "good_to_have": [
            "Kafka / RabbitMQ",
            "CI/CD pipelines",
            "Jenkins",
            "Git",
            "Design Patterns",
            "Domain-Driven Design (DDD)",
            "OAuth2 / JWT",
            "Terraform / IaC"
        ],
        "soft_skills": [
            "Strong communication",
            "Mentoring & coaching",
            "Stakeholder management",
            "Technical leadership",
            "Cross-team collaboration"
        ],
        "responsibilities": [
            "Lead architecture decisions for mission-critical, large-scale systems",
            "Design and own scalable microservices architectures end to end",
            "Mentor and coach development teams on engineering best practices",
            "Collaborate with product managers, business leaders, and stakeholders",
            "Evaluate and adopt new technologies aligned with business goals",
            "Conduct architecture reviews, code reviews, and design discussions",
            "Drive engineering excellence across delivery pods"
        ],
        "full_text": """
Java Architect — Wissen Technology

Location: Pune / Mumbai | Mode: Hybrid | Experience: 12+ years

About the Role:
We are looking for a seasoned Java Architect to lead architecture decisions for
mission-critical, large-scale systems at Wissen Technology. You will design and
own scalable microservices architectures, mentor development teams, and collaborate
closely with product and business stakeholders.

Must-Have Skills:
• Core Java, Java 8+ (streams, lambdas, functional interfaces)
• Spring Framework, Spring Boot
• Microservices architecture and design
• REST API design and implementation
• Hibernate / JPA for ORM
• SQL databases (PostgreSQL, MySQL, Oracle)
• NoSQL databases (MongoDB, Cassandra, Redis)
• Docker containerization
• Kubernetes orchestration
• Cloud platforms — AWS, Azure, or GCP (at least one)

Good-to-Have:
• Kafka or RabbitMQ for event-driven architecture
• CI/CD pipelines and Jenkins
• Git version control and branching strategies
• Design patterns and Domain-Driven Design (DDD)
• OAuth2, JWT for security
• Terraform or Infrastructure as Code

Key Responsibilities:
• Lead architecture decisions for mission-critical systems
• Design scalable microservices architectures
• Mentor and coach development teams
• Collaborate with product managers and business leaders
• Evaluate and adopt new technologies
• Conduct architecture and code reviews
• Drive engineering excellence across pods

Soft Skills:
• Strong communication and presentation skills
• Mentoring and coaching ability
• Stakeholder management
• Technical leadership
• Cross-functional collaboration
        """
    },

    "java-developer": {
        "id": "java-developer",
        "title": "Java Developer",
        "location": "Bangalore",
        "mode": "Hybrid",
        "experience": "5 to 8 years",
        "experience_min": 5,
        "experience_max": 8,
        "department": "Product Engineering",
        "must_have": [
            "Core Java",
            "Spring",
            "Spring Boot",
            "Hibernate / JPA",
            "Object-Oriented Programming (OOP)",
            "Data Structures & Algorithms (DSA)",
            "Design Patterns",
            "SQL databases",
            "NoSQL databases",
            "Debugging & troubleshooting"
        ],
        "good_to_have": [
            "REST APIs / Microservices",
            "Cloud platforms (AWS / Azure / GCP)",
            "Docker",
            "CI/CD pipelines",
            "Git",
            "Unit testing (JUnit, Mockito)",
            "Agile / Scrum"
        ],
        "soft_skills": [
            "Strong ownership and accountability",
            "Clear communication",
            "Strong work ethic",
            "Team collaboration",
            "Self-driven learning"
        ],
        "responsibilities": [
            "Design, develop, and maintain Java-based applications",
            "Write clean, testable, and well-documented code",
            "Participate in code reviews and design discussions",
            "Debug and resolve production issues efficiently",
            "Collaborate with cross-functional teams on feature delivery",
            "Contribute to technical documentation and knowledge sharing"
        ],
        "full_text": """
Java Developer — Wissen Technology

Location: Bangalore | Mode: Hybrid | Experience: 5 to 8 years

About the Role:
We are looking for a strong Java Developer to join our product engineering team
at Wissen Technology. You will work on building and maintaining high-quality
Java applications, collaborating with cross-functional teams, and taking ownership
of feature delivery from design to deployment.

Must-Have Skills:
• Core Java with strong fundamentals
• Spring Framework, Spring Boot
• Hibernate / JPA for data access
• Solid understanding of OOP principles
• Data Structures and Algorithms
• Design patterns
• SQL databases (PostgreSQL, MySQL)
• NoSQL databases (MongoDB, Redis)
• Strong debugging and troubleshooting skills

Good-to-Have:
• REST API design and microservices architecture
• Cloud platforms — AWS, Azure, or GCP
• Docker containerization
• CI/CD pipelines
• Git version control
• Unit testing with JUnit and Mockito
• Experience with Agile / Scrum methodologies

Key Responsibilities:
• Design, develop, and maintain Java applications
• Write clean, testable, well-documented code
• Participate in code reviews and design discussions
• Debug and resolve production issues
• Collaborate with cross-functional teams
• Contribute to documentation and knowledge sharing

Soft Skills:
• Strong ownership and accountability
• Clear and effective communication
• Strong work ethic and reliability
• Team-first collaboration mindset
• Self-driven continuous learning
        """
    }
}

COMPANY_CONTEXT = """
Wissen Technology — Company Overview

Founded: 2015
Headquarters: Global presence across US, UK, UAE, India, and Australia
Employees: 2000+
Type: Product Engineering Company

Who We Are:
Wissen Technology is a product engineering company that solves complex business
challenges for global enterprises. We build mission-critical systems with a focus
on engineering excellence, scalable architecture, and outcome-based delivery.

How We Work:
• Agile pods — small, autonomous teams with end-to-end ownership
• Outcome-based projects — measured by business impact, not just output
• Engineering-first culture — we value clean code, good design, and continuous learning
• Collaboration across geographies — our teams span US, UK, UAE, India, Australia

What Makes Us Different:
• Product engineering mindset — we think like product builders, not outsourced vendors
• Complex problem focus — we take on the hard challenges others avoid
• Mission-critical systems — our work runs in production at scale, 24/7
• Growth environment — engineers grow into architects, leads, and domain experts
• Global exposure — work with international clients and distributed teams

Engineering Culture:
• Regular tech talks and knowledge-sharing sessions
• Investment in learning and certifications
• Open-door leadership — flat hierarchy, accessible leadership
• Focus on developer experience and tooling
• Code quality is non-negotiable — reviews, testing, and automation are standard
"""


BUILTIN_JD_IDS = set(JDS.keys())


def get_jd(jd_id: str) -> dict | None:
    if jd_id in JDS:
        return JDS[jd_id]
    from lib.database import get_db_jd
    return get_db_jd(jd_id)


def get_all_jds() -> list[dict]:
    from lib.database import get_all_db_jds
    results = [
        {"id": jd["id"], "title": jd["title"], "location": jd["location"],
         "mode": jd["mode"], "experience": jd["experience"]}
        for jd in JDS.values()
    ]
    for jd in get_all_db_jds():
        results.append({
            "id": jd["id"], "title": jd["title"], "location": jd["location"],
            "mode": jd["mode"], "experience": jd["experience"]
        })
    return results


def get_all_jds_full() -> list[dict]:
    """Return full JD objects (for admin pages that need all fields)."""
    from lib.database import get_all_db_jds
    return list(JDS.values()) + get_all_db_jds()
