# KEFRICO Tontine

> Assistant WhatsApp pour créer, gérer et suivre des tontines.

**Statut :** 🚧 En développement — `Phase 0 — Foundation`

KEFRICO Tontine permet de gérer une tontine directement depuis WhatsApp, sans installer
d'application supplémentaire et sans avoir à apprendre une interface.

Le principe est simple :

> L'utilisateur parle naturellement à KEFRICO Tontine sur WhatsApp,
> et le système transforme ses messages en actions métier sécurisées.

---

## Sommaire

- [Le problème](#le-problème)
- [Expérience utilisateur](#expérience-utilisateur)
- [Principe fondamental](#principe-fondamental)
- [Architecture](#architecture)
- [Stack technique](#stack-technique)
- [Structure du projet](#structure-du-projet)
- [Modèle métier](#modèle-métier)
- [Règles d'ingénierie critiques](#règles-dingénierie-critiques)
- [Démarrage](#démarrage)
- [Webhook WhatsApp](#webhook-whatsapp)
- [Configuration](#configuration)
- [Feuille de route](#feuille-de-route)
- [Philosophie produit](#philosophie-produit)

---

## Le problème

Dans de nombreux groupes, associations, familles et communautés, les tontines sont encore
gérées avec des cahiers, des feuilles Excel, des groupes WhatsApp, des messages privés,
des confirmations manuelles et des calculs faits à la main.

Cela produit systématiquement les mêmes difficultés :

| Difficulté | Conséquence |
| --- | --- |
| Oublis de cotisation | Retards en chaîne sur les tours |
| Erreurs de calcul | Écarts de caisse |
| Suivi manuel des paiements | Personne ne sait qui a réellement payé |
| Absence de traçabilité | Litiges impossibles à arbitrer |
| Historique dispersé | Perte de mémoire d'un cycle à l'autre |
| Multiplication des tontines | Charge de gestion ingérable |

KEFRICO Tontine transforme WhatsApp en une interface simple de gestion de tontine.

---

## Expérience utilisateur

L'utilisateur interagit uniquement avec le bot WhatsApp.

```text
Utilisateur :
Bonjour

KEFRICO Tontine :
Bonjour 👋

Bienvenue sur KEFRICO Tontine.

Je peux vous aider à :
💰 consulter vos cotisations
📅 voir votre prochaine échéance
👥 gérer votre tontine
📊 consulter votre situation
➕ créer une tontine
❓ obtenir de l'aide

Que souhaitez-vous faire ?
```

Il peut aussi écrire naturellement :

```text
Combien dois-je cotiser cette semaine ?

Je veux créer une tontine de 10 personnes à 10 000 FCFA par semaine.

Qui n'a pas encore cotisé ?

Quand est mon prochain tour ?
```

Le bot comprend l'intention, récupère le contexte et déclenche le bon workflow métier.

L'objectif est de rester sur ce chemin :

```text
Utilisateur → WhatsApp → Compréhension → Action métier → Confirmation
```

et d'éviter autant que possible celui-ci :

```text
Menu → Sous-menu → Sous-sous-menu → Formulaire → Action
```

Les boutons WhatsApp sont utilisés uniquement lorsqu'ils simplifient réellement l'expérience.

---

## Principe fondamental

KEFRICO Tontine n'est pas un chatbot IA. C'est un système métier dont WhatsApp est l'interface.

Deux parties sont clairement séparées :

```text
Conversation / IA
        ↓
Compréhension de l'intention
        ↓
Services métier déterministes
        ↓
MongoDB
```

L'IA peut comprendre `"J'ai payé mes 10 000"`.
Elle ne décide **jamais** seule qu'un paiement est validé.

La validation financière appartient exclusivement au moteur métier et, à terme, aux
fournisseurs de paiement intégrés.

---

## Architecture

```text
                    UTILISATEUR
                         │
                         ▼
                     WhatsApp
                         │
                         ▼
             Meta WhatsApp Cloud API
                         │
                      Webhook
                         │
                         ▼
                ┌─────────────────┐
                │     FastAPI     │
                │     Python      │
                └────────┬────────┘
                         │
                         ▼
                Message Gateway
                         │
                         ▼
                 Intent Router
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
    Tontines         Paiements          Support
        │                │                │
        ├──────────┬─────┴──────┬─────────┤
        │          │            │         │
        ▼          ▼            ▼         ▼
     Cycles   Contributions   Ledger   Notifications
        │          │            │         │
        └──────────┴─────┬──────┴─────────┘
                         │
                         ▼
                      MongoDB
                         │
              ┌──────────┴─────────┐
              ▼                    ▼
            Redis                Workers
```

Le projet démarre sous forme de **modular monolith** : pas de microservices en V1, mais des
modules suffisamment isolés pour pouvoir être extraits plus tard si le besoin apparaît.

---

## Stack technique

### Backend

- Python 3.12+
- FastAPI / Uvicorn
- Pydantic v2 (+ Pydantic Settings)
- PyMongo Async
- HTTPX

### Données

- MongoDB (MongoDB Atlas en production)
- Replica set requis pour les transactions multi-documents sensibles

### Pas encore installés

Ajoutés seulement lorsqu'un besoin réel apparaîtra, pas avant :

- Redis — cache, rate limiting, locks, sessions conversationnelles
- Dramatiq — workers, traitements asynchrones

### Infrastructure

- Docker / Docker Compose

### Qualité

- Pytest
- Ruff
- MyPy ou Pyright
- pre-commit

### API externe

- Meta WhatsApp Cloud API (API officielle uniquement)

---

## Structure du projet

Arborescence cible :

```text
app/
├── main.py
│
├── api/
│   ├── health.py
│   └── webhooks/
│       └── whatsapp.py
│
├── core/
│   ├── config.py
│   ├── logging.py
│   ├── security.py
│   └── exceptions.py
│
├── infrastructure/
│   ├── database/
│   ├── redis/
│   ├── queue/
│   └── whatsapp/
│
├── modules/
│   ├── users/
│   ├── organizations/
│   ├── tontines/
│   ├── memberships/
│   ├── cycles/
│   ├── rounds/
│   ├── contributions/
│   ├── payments/
│   ├── ledger/
│   ├── conversations/
│   ├── notifications/
│   └── audit/
│
├── workers/
│
└── schemas/
```

Un module métier sépare généralement `models`, `schemas`, `repository`, `service` et
`exceptions`. Les routes HTTP ne contiennent pas de logique métier :

```text
router → service → repository
```

---

## Modèle métier

```text
Organization
     │
     └── WhatsAppAccount
              │
              ▼
             User
              │
              ▼
      TontineMembership
              │
              ▼
           Tontine
              │
        ┌─────┴─────┐
        ▼           ▼
      Cycle       Round
        │           │
        └─────┬─────┘
              ▼
        Contribution
              │
              ▼
           Payment
              │
              ▼
            Ledger
              │
              ▼
            Payout
```

Trois distinctions structurantes :

- **Tontine ≠ Cycle ≠ Round.** Un cycle est une période complète de tontine ; un round est
  une échéance à l'intérieur d'un cycle. Cela permet de conserver l'historique complet au
  démarrage d'un nouveau cycle.
- **User ≠ Membership.** Un utilisateur peut appartenir à plusieurs tontines, avec un rôle
  et une position différents dans chacune (`OWNER`, `ADMIN`, `MEMBER`).
- **Message ≠ Action métier.** Un message WhatsApp produit une intention, qui déclenche une
  action ; ce n'est pas l'action elle-même.

Statuts d'une tontine : `DRAFT`, `OPEN`, `ACTIVE`, `PAUSED`, `COMPLETED`, `CANCELLED`.

### Collections MongoDB prévues

```text
organizations          tontines               contributions
whatsapp_accounts      tontine_members        payments
users                  cycles                 payouts
whatsapp_contacts      rounds                 ledger_entries

conversations          notifications          webhook_events
messages               reminders              idempotency_keys
                                              audit_logs
```

Toutes les dates sont stockées en UTC, avec `created_at` / `updated_at` cohérents.

---

## Règles d'ingénierie critiques

### 1. Ledger financier

Les opérations financières ne sont **jamais** gérées par un simple champ `balance`.

À éviter :

```json
{ "user": "123", "balance": 50000 }
```

Le système conserve un journal append-only des mouvements :

```json
{
  "type": "CONTRIBUTION",
  "amount": 10000,
  "currency": "XOF",
  "member_id": "...",
  "tontine_id": "...",
  "round_id": "...",
  "payment_id": "...",
  "direction": "CREDIT",
  "status": "POSTED",
  "created_at": "..."
}
```

Types d'écritures : `CONTRIBUTION`, `PAYOUT`, `REFUND`, `REVERSAL`, `ADJUSTMENT`, `FEE`.

Le ledger est la référence financière du système. Une écriture validée n'est jamais
modifiée ni supprimée silencieusement — une correction produit une écriture compensatoire.

### 2. L'IA ne valide pas les paiements

Une contribution suit ces états :

```text
PENDING → DECLARED → VERIFIED
                  ↘ REJECTED / CANCELLED
```

Un utilisateur qui écrit `"J'ai payé"` produit `DECLARED`, **jamais** `VERIFIED`.

La vérification provient d'un administrateur, d'un webhook Mobile Money ou d'une autre
source explicitement fiable.

### 3. Idempotence

Tous les webhooks sont idempotents. Les providers rejouent leurs événements.

```text
Meta envoie l'événement A
        ↓
KEFRICO traite A
        ↓
Meta renvoie A
        ↓
KEFRICO détecte que A existe déjà
        ↓
acquittement, aucun deuxième traitement
```

Des index uniques protègent au minimum :

```text
whatsapp_message_id
provider_event_id
payment_reference
idempotency_key
```

Une contribution ne doit jamais être comptabilisée deux fois à cause d'un retry.

### 4. Webhooks courts

Un webhook fait le strict minimum avant de répondre :

```text
validation → idempotence → normalisation → mise en file → HTTP 200
```

Les traitements longs (dont les appels LLM) sont déportés dans les workers.

### 5. Sécurité et audit

Le numéro WhatsApp n'est pas une preuve d'identité suffisante pour les opérations
sensibles ; celles-ci pourront exiger un PIN, un OTP ou une confirmation explicite.

Chaque action importante est enregistrée dans `audit_logs` avec au minimum
`actor`, `action`, `resource`, `timestamp`, `correlation_id`, `metadata` — par exemple
`TONTINE_CREATED`, `MEMBER_ADDED`, `CONTRIBUTION_VERIFIED`, `PAYOUT_CREATED`.

Aucun secret n'est versionné. Les logs sont structurés, corrélés par `correlation_id`, et
ne contiennent jamais de token, PIN, OTP ou credential.

### 6. Redis n'est pas une source de vérité

Redis sert au cache, au rate limiting, aux locks courts, aux sessions conversationnelles,
aux OTP et aux files. Les données critiques restent dans MongoDB.

---

## Démarrage

### Prérequis

- Docker et Docker Compose
- [uv](https://docs.astral.sh/uv/) pour le développement hors conteneur
  (il installe lui-même Python 3.12)

### Démarrage avec Docker

```bash
git clone git@github.com:kefrico-dev/tontine-bot-whatsapp.git
cd tontine-bot-whatsapp

cp .env.example .env    # optionnel : le compose fonctionne sans

docker compose up --build
```

Le compose démarre un MongoDB en **replica set mono-nœud** (`rs0`), initialisé
automatiquement et de façon idempotente : aucune manipulation manuelle n'est nécessaire.
Le replica set est requis par les transactions multi-documents dont dépendra le ledger.

### Vérification

```bash
curl http://localhost:8000/health   # liveness  -> {"status":"ok"}
curl http://localhost:8000/ready    # readiness -> {"status":"ready","services":{"mongodb":"up"}}
```

`/health` ne fait aucune I/O. `/ready` interroge MongoDB et répond **503** avec
`{"status":"not_ready","services":{"mongodb":"down"}}` si la base ne répond pas.

### Développement hors conteneur

```bash
uv sync                                  # installe Python 3.12 + dépendances
uv run uvicorn app.main:app --reload     # http://localhost:8000

uv run ruff check .                      # lint
uv run ruff format .                     # formatage
uv run mypy                              # typage
uv run pytest                            # tests
```

### URI MongoDB : hôte ou conteneur

Le replica set s'annonce sous le nom `mongo`, qui n'est résoluble qu'à l'intérieur du
réseau Docker. L'URI diffère donc selon l'endroit d'où l'on se connecte :

| Depuis | `MONGODB_URI` |
| --- | --- |
| un conteneur du compose | `mongodb://mongo:27017/?replicaSet=rs0` |
| l'hôte (Windows, tests, `uv run`) | `mongodb://localhost:27017/?directConnection=true` |
| MongoDB Atlas | `mongodb+srv://<user>:<password>@<cluster>/?retryWrites=true&w=majority` |

`directConnection=true` court-circuite la découverte du replica set et évite que le driver
tente de résoudre `mongo` depuis l'hôte.

Si `.env` définit `MONGODB_URI` (une instance Atlas par exemple), `docker compose` utilise
cette valeur à la place du MongoDB local.

Les tests unitaires n'ont besoin d'aucune base. Les tests d'intégration
(`uv run pytest -m integration`) s'exécutent si une base est joignable, et sont ignorés
sinon.

---

## Webhook WhatsApp

### Routes

| Route | Rôle |
| --- | --- |
| `GET /webhooks/whatsapp` | Vérification Meta. Répond le `hub.challenge` en texte brut si `hub.mode=subscribe` et que le verify token correspond ; **403** sinon |
| `POST /webhooks/whatsapp` | Réception des événements. Vérifie `X-Hub-Signature-256` sur le corps brut, normalise, déduplique, enregistre, répond |

Codes de retour du POST, et ce que Meta en fait :

| Situation | Code | Meta rejoue ? |
| --- | --- | --- |
| Événement traité, doublon, ou payload non pertinent | `200` | non |
| Signature absente ou invalide | `403` | oui |
| JSON malformé | `400` | oui, sans effet |
| MongoDB indisponible ou index absents | `503` | oui — c'est voulu, rien n'est perdu |
| Envoi de la réponse échoué | `200` | non — rejouer ne réparerait pas l'envoi et risquerait un doublon |

### Test local

```bash
uv run uvicorn app.main:app --reload

# Vérification (le challenge est renvoyé tel quel)
curl "http://localhost:8000/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$META_VERIFY_TOKEN&hub.challenge=1234"

# Réception : la signature doit être calculée sur le corps exact
BODY='{"object":"whatsapp_business_account","entry":[]}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$META_APP_SECRET" | awk '{print $2}')
curl -X POST http://localhost:8000/webhooks/whatsapp   -H "X-Hub-Signature-256: sha256=$SIG"   -H "Content-Type: application/json"   -d "$BODY"
```

### Exposer le webhook à Meta

Meta doit joindre le webhook depuis Internet. En développement, un tunnel suffit :

```bash
ngrok http 8000
```

L'URL publique change à chaque redémarrage d'ngrok : le webhook Meta doit être
reconfiguré à chaque session.

### Configuration côté Meta

Dans `Cas d'utilisation → Connecter à WhatsApp → Configuration de base → Étape 1` :

1. **Callback URL** : `https://<sous-domaine>.ngrok-free.app/webhooks/whatsapp`
2. **Verify token** : la valeur de `META_VERIFY_TOKEN` de votre `.env`
3. Cliquer sur **Vérifier et enregistrer** — Meta appelle le `GET` et attend le challenge
4. S'abonner au champ **`messages`** (il couvre les messages entrants et les statuts de livraison)
5. Ajouter son numéro dans la liste des destinataires autorisés du numéro de test

Les numéros de téléphone ne sont jamais journalisés en entier, seuls les quatre
derniers chiffres apparaissent. Les jetons, secrets et URI de base ne sont jamais
journalisés du tout — le log d'accès d'uvicorn est désactivé pour cette raison,
puisqu'il imprimerait le verify token présent dans la query string.

---

## Configuration

Toute la configuration passe par variables d'environnement, validées au démarrage par
Pydantic Settings. L'application échoue immédiatement (fail fast) si une variable
obligatoire manque en production.

| Variable | Phase | Description |
| --- | --- | --- |
| `ENVIRONMENT` | 0 | `local`, `staging` ou `production` |
| `LOG_LEVEL` | 0 | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `MONGODB_URI` | 0 | URI de connexion MongoDB |
| `MONGODB_DATABASE` | 0 | Nom de la base (défaut : `kefrico_tontine`) |
| `META_VERIFY_TOKEN` | 1 | Token de vérification du webhook Meta |
| `META_APP_SECRET` | 1 | Secret applicatif Meta (vérification de signature) |
| `WHATSAPP_ACCESS_TOKEN` | 1 | Token d'accès Meta WhatsApp Cloud API |
| `WHATSAPP_PHONE_NUMBER_ID` | 1 | Identifiant du numéro WhatsApp émetteur |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | 1 | Identifiant du compte WhatsApp Business |

Les variables de Phase 1 sont **optionnelles** tant que l'intégration WhatsApp n'existe
pas : la fondation ne doit pas refuser de démarrer pour une configuration qui ne la
concerne pas encore. En production, `MONGODB_URI` doit désigner une instance distante —
l'application refuse de démarrer sur `localhost`.

Un fichier `.env.example` contient uniquement des valeurs factices.
**Aucun secret ne doit jamais être commité.**

---

## Feuille de route

| Version | Contenu |
| --- | --- |
| **Phase 0** | Foundation — FastAPI, MongoDB, Redis, Docker, config, logging, healthcheck, tests, CI |
| **Phase 1** | WhatsApp Core — vérification webhook Meta, signature, normalisation, idempotence, envoi de messages |
| **Phase 2** | Tontine Core — tontines, membres, cycles, rounds, contributions, historique |
| **V1.1** | Rappels intelligents |
| **V1.2** | Dashboard administrateur |
| **V1.3** | Mobile Money |
| **V1.4** | Notes vocales |
| **V1.5** | KEFRICO AI — langage naturel |
| **V2** | Multi-organisations / SaaS |
| **V3** | Écosystème KEFRICO |

### Périmètre V1

Recevoir et répondre à un message WhatsApp · créer automatiquement un utilisateur ·
créer une tontine · rejoindre une tontine · consulter ses tontines · gérer les membres ·
définir le montant et la fréquence des cotisations · gérer les cycles et les tours ·
consulter la prochaine échéance · enregistrer une contribution · consulter l'historique ·
envoyer des rappels · conserver les conversations · journaliser les actions importantes.

La V1 peut fonctionner sans intégration automatique d'un fournisseur de paiement.

### Premier jalon

```text
Utilisateur WhatsApp
      ↓
"Bonjour"
      ↓
Meta Cloud API
      ↓
FastAPI — webhook validé
      ↓
message enregistré dans MongoDB
      ↓
"Bienvenue sur KEFRICO Tontine 👋"
```

Les workflows métier avancés ne démarrent qu'une fois ce jalon atteint.

---

## Philosophie produit

**Simple** — l'utilisateur n'a pas besoin d'apprendre à utiliser le produit.

**Fiable** — une opération financière n'est jamais comptée deux fois.

**Traçable** — chaque opération importante peut être expliquée.

**Conversationnel** — WhatsApp est l'interface principale.

**Évolutif** — le produit doit pouvoir passer d'un bot à une plateforme multi-organisations.

> Lorsque simplicité et sophistication entrent en conflit, choisir la solution la plus
> simple qui conserve la sécurité, la fiabilité et les capacités d'évolution nécessaires.

---

## Contribuer

Le projet avance par phases cohérentes. Avant tout commit :

```bash
ruff check .
pytest
```

Aucun module financier n'est considéré terminé sans tests. Chaque bug financier corrigé
donne lieu à un test de non-régression.

Les conventions détaillées et les contraintes d'architecture sont décrites dans
[CLAUDE.md](CLAUDE.md).

---

## KEFRICO

**KEFRICO Tontine** fait partie de la vision KEFRICO : construire des outils numériques
simples, fiables et adaptés aux usages réels des entreprises et des communautés.
