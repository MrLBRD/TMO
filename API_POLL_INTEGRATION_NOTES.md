# Notes d’intégration — Endpoint `POST /api/poll`

Ce document décrit **ce que l’application TMO (Python) envoie** vers votre module (gestion étiquettes/commandes) afin que vous puissiez implémenter l’endpoint **sans avoir accès au code** de l’app.

---

## 1) Objectif

À chaque **début** et **fin** d’enregistrement vidéo (déclenché par QR ou par démarrage manuel), TMO appelle un endpoint HTTP côté “site” afin de notifier l’état.

---

## 1bis) Format du QR Code

Le QR code utilisé pour déclencher l’enregistrement encode :

- `Tk-{order_id}`

Où :

- `order_id` est l’identifiant de commande (généralement **10 caractères**)

Exemple :

- `Tk-ABC1234567`

Important :

- Le préfixe `Tk-` est **obligatoire**.
- Tout QR code ne respectant pas ce format est **ignoré** (objectif : éviter les déclenchements accidentels sur une suite de chiffres / autre code).
- TMO extrait l’`order_id` à partir de cette valeur.
- C’est cet `order_id` extrait qui est envoyé dans le JSON vers `POST /api/poll`.

---

## 2) URL appelée

TMO peut fonctionner selon 2 modes :

### Mode normal (recommandé)

- Dans l’écran de configuration TMO, l’opérateur renseigne :
  - `Site` : ex. `https://example.com`
  - `Clé API` : ex. `my-secret-key`

Dans ce mode, l’URL réellement appelée est :

- `POST {Site}/api/poll`

Exemple :

- `POST https://example.com/api/poll`

### Mode “override” (avancé)

- Dans l’écran de configuration TMO, l’opérateur peut aussi renseigner un champ `API URL`.
- Si `API URL` est renseignée, elle **a priorité** sur `Site`.

---

## 3) Méthode, headers, body

### Méthode

- `POST`

### Headers

- `Content-Type: application/json`
- `X-API-Key: <clé>`
  - Présent **uniquement** si l’opérateur a renseigné la “Clé API” dans TMO.

### Body (JSON)

Champs envoyés :

- `order_id` (string)
  - Identifiant de commande.
  - Attendu typiquement : **10 caractères**.
- `timestamp` (string)
  - Timestamp **UTC** au format ISO 8601.
  - Exemple: `2025-12-12T22:39:12.123456+00:00`
- `status` (string)
  - Valeurs actuellement utilisées :
    - `video_started`
    - `video_stopped`

Exemple complet :

```json
{
  "order_id": "ABC1234567",
  "timestamp": "2025-12-12T22:39:12.123456+00:00",
  "status": "video_started"
}
```

---

## 4) Quand les appels sont émis

- `video_started`
  - Quand TMO démarre un enregistrement (QR valide ou bouton START).
- `video_stopped`
  - Quand TMO stoppe un enregistrement (bouton STOP ou scan d’une **nouvelle** commande).

Cas “scan commande suivante” :

- TMO stoppe l’enregistrement courant => `video_stopped` pour la commande en cours
- Puis démarre immédiatement le suivant => `video_started` pour la nouvelle commande

---

## 5) Gestion des réponses / erreurs

- TMO considère que l’appel est OK si l’endpoint répond en **2xx**.
- Timeout HTTP côté TMO : environ **2 secondes**.
- En cas d’erreur réseau / non-2xx :
  - TMO affiche “Erreur Réseau” brièvement dans l’UI.
  - Puis l’UI revient à l’état précédent.

Le body de la réponse n’est **pas exploité** par TMO (vous pouvez renvoyer un JSON ou juste un `200 OK`).

---

## 6) Recommandations d’implémentation côté “site”

- **Authentification** :
  - Si vous activez l’auth, vérifiez `X-API-Key`.
  - Rejetez avec `401/403` si la clé ne correspond pas.
- **Validation** :
  - `order_id` string non vide (souvent 10 chars)
  - `status` ∈ {`video_started`, `video_stopped`}
  - `timestamp` parseable
- **Idempotence** (optionnel mais utile) :
  - Vous pouvez accepter des doublons (réseau instable) et dédupliquer si besoin.

---

## 7) Exemple curl

```bash
curl -X POST "https://example.com/api/poll" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: my-secret-key" \
  -d '{"order_id":"ABC1234567","timestamp":"2025-12-12T22:39:12+00:00","status":"video_started"}'
```
