# Google Cloud Run deployment

SDOC Clearview is deployed as one container: FastAPI serves both the API and
the compiled React application. The image carries a read-only 526-case demo
baseline. At startup, the service creates a writable working copy under
`/tmp/sdoc-data`.

## Runtime behaviour

- One public URL serves the interface and `/api` routes.
- Every new Cloud Run instance starts with the committed demo baseline.
- **Reset Demo** restores that instance to the same baseline.
- Operator changes and uploaded simulations are demo-session data. They are
  discarded when Cloud Run replaces or stops the instance.
- The service is intentionally limited to one instance because SQLite is not a
  shared database.

## One-time Google Cloud setup

Choose a project and enable the required services:

```powershell
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

Create the OpenRouter secret without putting the key in Git or the image:

```powershell
$keyFile = Join-Path $env:TEMP "sdoc-openrouter-key.txt"
[System.IO.File]::WriteAllText($keyFile, (Read-Host "OpenRouter API key"))
gcloud secrets create openrouter-api-key --data-file=$keyFile
Remove-Item -LiteralPath $keyFile
```

If the secret already exists, add a new version instead:

```powershell
$keyFile = Join-Path $env:TEMP "sdoc-openrouter-key.txt"
[System.IO.File]::WriteAllText($keyFile, (Read-Host "OpenRouter API key"))
gcloud secrets versions add openrouter-api-key --data-file=$keyFile
Remove-Item -LiteralPath $keyFile
```

Grant the Cloud Run runtime service account access to the secret. Replace the
project number with the value returned by the first command:

```powershell
gcloud projects describe YOUR_PROJECT_ID --format="value(projectNumber)"
gcloud secrets add-iam-policy-binding openrouter-api-key --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
```

## Deploy

Run this from the repository root:

```powershell
gcloud run deploy sdoc-clearview `
  --source . `
  --region asia-southeast1 `
  --allow-unauthenticated `
  --port 8080 `
  --cpu 1 `
  --memory 2Gi `
  --concurrency 8 `
  --min-instances 0 `
  --max-instances 1 `
  --timeout 900 `
  --set-env-vars "LLM_BACKEND=operational,CLASSIFICATION_FALLBACK_THRESHOLD=0.80,WORKERS=4" `
  --set-secrets "OPENROUTER_API_KEY=openrouter-api-key:latest"
```

Cloud Build builds the repository's `Dockerfile`, deploys it, and prints the
public service URL.

## Verify the deployed demo

Replace `SERVICE_URL` with the URL printed by the deployment:

```powershell
Invoke-RestMethod "SERVICE_URL/api/health"
Invoke-RestMethod "SERVICE_URL/api/config"
```

Then open `SERVICE_URL` and verify:

1. Work Queue contains the frozen demo cases.
2. A case opens and its attachments render.
3. **Simulate Email** processes one small example.
4. **Reset Demo** restores the 526-case baseline.

## Updating the service

Commit and push the change, then run the same `gcloud run deploy` command.
Cloud Run creates a new revision and moves traffic to it after startup succeeds.

## Production upgrade path

This configuration is intentionally a resettable Hackathon demo. For durable
operator state or multiple instances, move the working database to Cloud SQL
and uploaded files to Cloud Storage before increasing `max-instances`.
