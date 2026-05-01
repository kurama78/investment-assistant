# Render Auto Deploy Fallback

This repository includes `.github/workflows/render-deploy.yml` as a fallback when
Render's native GitHub auto deploy does not trigger reliably.

## One-time setup

1. Open the GitHub repository settings.
2. Go to `Secrets and variables` -> `Actions`.
3. Add a repository secret named `RENDER_API_KEY`.
4. Save the secret.

## How it works

- Every push to `main` triggers the GitHub Actions workflow.
- The workflow calls the Render API directly.
- It triggers a deploy for service `srv-d7q17rf7f7vs73cgi7k0`.

## Manual retry

If you want to trigger it manually:

1. Open the repository `Actions` tab.
2. Select `Deploy to Render`.
3. Click `Run workflow`.
