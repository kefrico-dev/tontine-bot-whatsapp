# CLAUDE.md — KEFRICO Tontine

Ce fichier définit **comment travailler** sur ce projet.
Le contexte produit (vision, architecture, modèle métier, feuille de route) est décrit dans
[README.md](README.md) — le lire avant toute modification structurante.

---

## 1. Mission

KEFRICO Tontine est un bot WhatsApp permettant de créer, gérer et suivre des tontines
directement depuis WhatsApp. Le projet est développé en Python.

Ce n'est **pas** un simple chatbot : c'est un système métier dont WhatsApp est l'interface.

Priorités, dans cet ordre :

1. simplicité utilisateur
2. sécurité
3. fiabilité financière
4. traçabilité
5. maintenabilité
6. architecture évolutive

---

## 2. Phase actuelle

Le repository vient d'être créé et est pratiquement vide.
**Ne pas tenter de développer l'intégralité du produit.** On avance phase par phase.

```text
PHASE 0 — FOUNDATION   ← en cours
structure du repository · FastAPI · configuration · MongoDB · Redis · Docker
logging · healthcheck · tests · lint · typecheck · CI basique

PHASE 1 — WHATSAPP CORE
vérification webhook Meta · réception événements · validation signature
normalisation message · idempotence · envoi message texte · premier échange WhatsApp ↔ Python

PHASE 2 — TONTINE CORE
```

Aucune logique tontine, aucune IA, aucune intégration de paiement tant que la Phase 1
n'est pas atteinte.

---

## 3. Stack imposée

```text
Python 3.12+        FastAPI            Pydantic v2 / Pydantic Settings
PyMongo Async       MongoDB            Redis
Dramatiq            HTTPX              Pytest
Ruff                Docker             Docker Compose
```

- Éviter **Motor** pour les nouveaux développements (PyMongo Async à la place).
- Ne pas ajouter de dépendance importante sans justification.
- Toujours chercher la solution la plus simple qui répond correctement au besoin.

---

## 4. Architecture imposée

**Modular monolith.** Pas de microservices en V1 sauf demande explicite.

```text
WhatsApp → Meta Cloud API → FastAPI → Message Gateway → Intent Router
         → Domain Services → MongoDB
```

L'arborescence cible (`app/api`, `app/core`, `app/infrastructure`, `app/modules`,
`app/workers`, `app/schemas`) est décrite dans le README.

Un module métier sépare généralement : `models`, `schemas`, `repository`, `service`,
`exceptions`. Ne pas créer de couches inutiles uniquement pour respecter un pattern.

Les routes HTTP ne contiennent **pas** de logique métier :

```text
router → service → repository
```

La route valide, appelle le service, transforme la réponse. Rien de plus.

---

## 5. Règles critiques — non négociables

### 5.1 Ledger financier

Interdit comme source de vérité :

```python
user.balance += amount
```

Toute opération financière produit une écriture de ledger explicable, autant que possible
**append-only** : `CONTRIBUTION`, `PAYOUT`, `REFUND`, `REVERSAL`, `ADJUSTMENT`, `FEE`.

Une écriture validée n'est jamais supprimée ni modifiée silencieusement. Une correction
produit une opération compensatoire (reversal).

### 5.2 L'IA ne valide jamais un paiement

`"J'ai envoyé 10 000"` peut produire une contribution `DECLARED`.
**Jamais** `VERIFIED`. La vérification vient d'un administrateur, d'un webhook Mobile Money
ou d'une autre source explicitement fiable.

Le LLM peut : classifier une intention, extraire des paramètres, reformuler, expliquer, résumer.
Le LLM ne doit pas : valider un paiement, écrire directement dans MongoDB, décider d'un
montant, changer un bénéficiaire, exécuter une opération sensible sans validation métier.

Toute sortie de LLM est validée par un schéma Pydantic.

Favoriser les règles déterministes, les intentions, les state machines et les services
métier **avant** d'envisager un LLM.

### 5.3 Idempotence

Tous les webhooks sont idempotents. Les providers rejouent leurs événements.

```text
receive → validate → check external_event_id
        → déjà traité ? oui : acquitter et ignorer / non : traiter
```

Index uniques au minimum sur : `whatsapp_message_id`, `provider_event_id`,
`payment_reference`, `idempotency_key`.

Une contribution ne doit jamais être comptabilisée deux fois à cause d'un retry.

### 5.4 Webhooks courts

```text
validation → idempotence → normalisation → mise en file si nécessaire → HTTP 200
```

Les traitements longs vont dans les workers. Ne pas appeler un LLM à plusieurs secondes de
latence dans le chemin critique du webhook si cela peut être évité.

### 5.5 WhatsApp — API officielle uniquement

Utiliser **Meta WhatsApp Cloud API**.
Interdits : `whatsapp-web.js`, Selenium, automation navigateur, API non officielle.

```text
GET  /webhooks/whatsapp   → vérification Meta
POST /webhooks/whatsapp   → réception des événements
```

Toujours vérifier la signature Meta avant de faire confiance au payload.
Ne jamais logger les tokens Meta.

### 5.6 Redis n'est pas une source de vérité

Redis : cache, rate limiting, locks courts, sessions conversationnelles, queues, OTP,
state temporaire. Les données critiques restent dans MongoDB.

### 5.7 Message ≠ action métier

```text
Message  : "Je veux créer une tontine."
Intent   : CREATE_TONTINE
Action   : tontine_service.start_creation(...)
```

Conserver la distinction `conversation` / `message` / `intent` / `business action`.

---

## 6. MongoDB

MongoDB est la base principale, conçue pour tourner sur Atlas en production.
Pour les transactions multi-documents critiques, considérer qu'un replica set est disponible.

- `ObjectId` lorsque pertinent.
- `created_at` / `updated_at` cohérents sur tous les documents.
- Dates stockées en **UTC**.

Les collections prévues sont listées dans le README.

---

## 7. Autorisations

Un membre de tontine (`TontineMembership`) est distinct d'un `User`. Un utilisateur peut
appartenir à plusieurs tontines avec des rôles différents : `OWNER`, `ADMIN`, `MEMBER`.

Ne pas coder les autorisations dans les routes. Centraliser la logique d'autorisation métier.

Le numéro WhatsApp n'est pas une preuve d'identité suffisante pour les opérations sensibles
(PIN / OTP / confirmation explicite à prévoir).

---

## 8. Audit et logs

Les actions importantes sont enregistrées dans `audit_logs` : `TONTINE_CREATED`,
`MEMBER_ADDED`, `MEMBER_REMOVED`, `CONTRIBUTION_DECLARED`, `CONTRIBUTION_VERIFIED`,
`PAYMENT_RECEIVED`, `PAYOUT_CREATED`, `PAYOUT_VERIFIED`, `ROUND_CHANGED`, `TONTINE_CANCELLED`.

Une entrée doit permettre de comprendre : qui, a fait quoi, sur quelle ressource, quand,
dans quel contexte.

Logs **structurés**, avec `correlation_id` permettant de suivre une requête à travers :
webhook → service → database → worker → envoi WhatsApp.

Ne jamais logger : token, PIN, OTP, credential, payload financier sensible complet.

---

## 9. Secrets

Ne jamais commiter : `.env`, tokens, mots de passe, credentials, clés privées, URI MongoDB
avec credentials, access token Meta.

Maintenir un `.env.example` avec uniquement des valeurs factices.
Configuration typée via Pydantic Settings, **fail fast** au démarrage si une variable
obligatoire manque en production.

---

## 10. Erreurs

Interdit :

```python
except Exception:
    pass
```

Les erreurs attendues ont des exceptions métier explicites : `TontineNotFound`,
`MembershipNotFound`, `UnauthorizedTontineAction`, `ContributionAlreadyExists`,
`InvalidRound`, `PaymentAlreadyProcessed`.

Les réponses API ne divulguent aucun détail interne.

---

## 11. Tests

Aucun module financier important n'est terminé sans tests. Couvrir notamment :

```text
création tontine · ajout membre · double ajout membre · création cycle · création round
contribution · double contribution · idempotence webhook · rollback transaction
permissions · ledger · reversal
```

Chaque bug financier corrigé donne lieu à un test de non-régression.

Ne pas supposer qu'une fonctionnalité marche parce que le code compile : tester réellement
les invariants critiques.

---

## 12. Style Python

Simple, typé, lisible, explicite, testable.

- Type hints partout ; Pydantic aux frontières du système.
- Éviter les abstractions excessives et les fonctions gigantesques.
- Éviter les modules de plusieurs centaines de lignes quand la responsabilité peut être
  naturellement séparée.
- Architecture async.

---

## 13. Git et méthode de travail

Avant un commit :

```bash
ruff check .
# typecheck
pytest
```

- Travailler par phases cohérentes ; garder le repository propre.
- Ne jamais faire un changement massif non demandé dans une phase ciblée.
- Ne pas supprimer ni réécrire du code existant sans en comprendre l'impact.

Avant une modification importante :

1. inspecter le repository
2. comprendre l'existant
3. expliquer brièvement le plan
4. identifier les risques
5. effectuer les changements
6. lancer les vérifications
7. corriger les problèmes
8. fournir un rapport final

---

## 14. Règle finale

> Lorsque simplicité et sophistication entrent en conflit, choisir la solution la plus
> simple qui conserve la sécurité, la fiabilité et les capacités d'évolution nécessaires.

KEFRICO Tontine doit devenir un produit robuste. Il n'a pas besoin de devenir inutilement
complexe.
