Deploy the asset planner: commit all changes, push to GitHub, rebuild Docker image, and push to Docker Hub.

**Commit message:** $ARGUMENTS

## Steps

1. If $ARGUMENTS is empty, ask Nico for a one-line description of what changed before proceeding.

2. Stage all changes and commit:
   ```bash
   git add .
   git commit -m "<commit message>\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
   ```

3. Push to GitHub:
   ```bash
   git push
   ```

4. Rebuild the Docker image and restart the local container:
   ```bash
   docker compose up --build -d
   ```

5. Tag and push to Docker Hub:
   ```bash
   docker tag printer-planner:latest nickvdw111/printer-planner:latest
   echo "$DOCKER_PAT" | docker login -u nickvdw111 --password-stdin
   docker push nickvdw111/printer-planner:latest
   ```
   Note: `DOCKER_PAT` must be set in the shell environment. If it is not set, read it from `~/.docker/pat` (a plain text file, not committed to git).

6. Confirm to Nico with:
   - Git commit hash
   - GitHub push status
   - Docker Hub image digest
   One short summary, no fuss.

**Rules:**
- Never skip the commit step — do not push to Docker Hub without a corresponding git commit.
- If any step fails, stop and report the error immediately.
- Do not proceed past step 3 if git push fails.
