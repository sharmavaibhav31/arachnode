# Resume Parser — Before & After Email Examples

This document shows the personalization improvement when
resume context is passed to the Ollama email generator.

The key difference is in the product observation sentence
that Ollama generates. Before this feature, Ollama only knew
about the company. After this feature, Ollama knows about
both the company AND the candidate.

---

## Example 1 — Backend Engineer applying to Supabase

### Candidate Resume (parsed output)

- skills: python, fastapi, docker, kubernetes, postgresql
- years_experience: 5
- recent_role: senior backend engineer
- prompt_snippet: Role: Senior Backend Engineer | Experience: 5+ years | Skills: python, fastapi, docker, kubernetes, postgresql

### BEFORE — Without resume (generic)

Subject: Interested in Backend Engineer role at Supabase

Hi Jane,

Your open-source Postgres platform has redefined how developers
think about scalable database infrastructure.

I'd love to discuss the Backend Engineer role at Supabase.

GitHub: github.com/divyanshi
Stack: Python, FastAPI

Best regards,
Divyanshi

Ollama generated: "Your open-source Postgres platform has redefined
how developers think about scalable database infrastructure."

Problem: Talks only about the company. Says nothing about the candidate.
Every applicant gets the exact same observation sentence.

---

### AFTER — With resume (personalized)

Subject: Interested in Backend Engineer role at Supabase

Hi Jane,

As a Senior Backend Engineer with 5 years building FastAPI
microservices and managing PostgreSQL at scale, your open-source
Postgres platform is exactly the kind of infrastructure I have
been working with in production.

I'd love to discuss the Backend Engineer role at Supabase.

GitHub: github.com/divyanshi
Stack: Python, FastAPI, Docker, Kubernetes

Best regards,
Divyanshi

Ollama generated: "As a Senior Backend Engineer with 5 years building
FastAPI microservices and managing PostgreSQL at scale, your open-source
Postgres platform is exactly the kind of infrastructure I have been
working with in production."

Improvement:
- Connects candidate background to the company product
- Mentions actual skills and experience from the resume
- Feels written by a real person not a template

---

## Example 2 — Frontend Developer applying to Vercel

### Candidate Resume (parsed output)

- skills: javascript, react, typescript, nodejs, css
- years_experience: 3
- recent_role: frontend developer
- prompt_snippet: Role: Frontend Developer | Experience: 3+ years | Skills: javascript, react, typescript, nodejs, css

### BEFORE — Without resume (generic)

Subject: Interested in Frontend Engineer role at Vercel

Hi Mark,

Vercel's edge deployment model has fundamentally changed
how frontend teams ship to production.

I'd love to discuss the Frontend Engineer role at Vercel.

GitHub: github.com/divyanshi
Stack: React, TypeScript

Best regards,
Divyanshi

Ollama generated: "Vercel's edge deployment model has fundamentally
changed how frontend teams ship to production."

Problem: Generic. No mention of the candidate at all.

---

### AFTER — With resume (personalized)

Subject: Interested in Frontend Engineer role at Vercel

Hi Mark,

As a Frontend Developer with 3 years shipping React and TypeScript
applications, Vercel's edge deployment model directly solves the
performance bottlenecks I have been working around in production.

I'd love to discuss the Frontend Engineer role at Vercel.

GitHub: github.com/divyanshi
Stack: React, TypeScript, Node.js

Best regards,
Divyanshi

Ollama generated: "As a Frontend Developer with 3 years shipping React
and TypeScript applications, Vercel's edge deployment model directly
solves the performance bottlenecks I have been working around in
production."

Improvement:
- Candidate role and experience mentioned naturally
- Connected to a real pain point the candidate has faced
- Recruiter can immediately see the relevance

---

## Sample Parsed Resume Output

Running the parser on a real resume text gives:

Role: software engineer
Experience: 5
Skills: ['python', 'fastapi', 'docker', 'postgresql']
Prompt snippet: Role: Software Engineer | Experience: 5+ years | Skills: python, fastapi, docker, postgresql

This snippet gets injected into the Ollama prompt to generate
the personalized observation sentence.

---

## Summary

Without Resume:
- Ollama input: Company product description only
- Generated sentence: About the company only
- Personalization: None
- Recruiter impression: Generic mass outreach

With Resume:
- Ollama input: Company product + candidate background
- Generated sentence: Connects candidate to company
- Personalization: Skills + experience + role included
- Recruiter impression: Relevant and specific