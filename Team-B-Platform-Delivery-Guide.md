# TriageIQ — Team B Guide: Platform, Delivery & Ops

> **Read Part 0 of `Team-A-Application-ML-Guide.md` first.** It is the shared contract for both teams: architecture, repo layout, cloud-ready rules, coding practices, service contracts, env vars, DB schema, metric names and the dataset.
> This guide covers only Team B's phases. Anything in Part 0 is a rule here too.

**Owners**
- **B-Delivery developer**: B1 Jenkins, B2 CI pipeline, B3 DevSecOps, B8 retrain automation
- **B-Infra developer**: B4 public access, B5 IaC, B6 Kubernetes, B7 monitoring and logging
- **Both**: B9 drift demo and final hardening

**What Team B owns, in one sentence**: everything that builds, checks, deploys, exposes, observes and automatically retrains Team A's services, **without editing Team A's service code**. If you need a code change in a service, open an issue for Team A.

**Order** (same rules as Part 0.3: a gate must pass before the next phase starts)
```
Phase 0 (joint) ─┬─ B1 → B2 → B3            (B-Delivery)
                 └─ B4 → B5 → B6            (B-Infra)
                         ══ DevOps POC gate (Part 0.2.2) ══
                    B7 → B8 → B9            (MLOps phase; B8 needs Team A's A9)
```

---

## Phase 0 — Team B's part (same session as Team A)

1. On the **demo machine** (the one PC that runs the integrated stack and Jenkins), install:
   - Docker Desktop (WSL2 backend)
   - Git
   - Terraform CLI
   - `kind`
   - `kubectl`
   - Python 3.11
2. Create the empty `ops/`, `deploy/` and `infra/` directories from Part 0.4, each with a one-line `README.md` saying what goes there.
3. Review Team A's first `docker-compose.yml` against Part 0.5, then run **Gate 0** for Team A.
4. Decide who holds the Jenkins admin password and the `.env` for the demo machine (one person, kept in a password manager).

---

## B1 — Jenkins as code (B-Delivery)

**Goal**: one command starts a fully configured Jenkins. **No setup wizard, no clicking.** Deleting the container and its volume and starting again gives the same Jenkins.

**Files**: `ops/jenkins/Dockerfile`, `ops/jenkins/plugins.txt`, `ops/jenkins/casc.yaml`, plus the `jenkins` service in `docker-compose.yml`.

**`ops/jenkins/Dockerfile`**
```dockerfile
FROM jenkins/jenkins:<pinned-lts>-jdk17          # pin an exact LTS tag, never "lts"
USER root
# Docker CLI + compose plugin from Docker's official apt repo (docs.docker.com/engine/install/debian)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg python3 \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
 && rm -rf /var/lib/apt/lists/*
USER jenkins
COPY ops/jenkins/plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
COPY ops/jenkins/casc.yaml /usr/share/jenkins/casc.yaml
ENV CASC_JENKINS_CONFIG=/usr/share/jenkins/casc.yaml \
    JAVA_OPTS=-Djenkins.install.runSetupWizard=false
```
`python3` is there so `scripts/smoke_test.py` (stdlib only) can run on the controller.

**`ops/jenkins/plugins.txt`** (after the first successful build, pin versions with `plugin:version`)
```
configuration-as-code
job-dsl
workflow-aggregator
git
docker-workflow
generic-webhook-trigger
credentials-binding
timestamper
ws-cleanup
pipeline-stage-view
```

**`ops/jenkins/casc.yaml`**
- JCasC replaces `${VAR}` with environment variables, and the container gets them from `.env`.
- Check the Job DSL syntax against your Jenkins at `http://127.0.0.1:8090/plugin/job-dsl/api-viewer/index.html`.

```yaml
jenkins:
  systemMessage: "TriageIQ CI: configured as code. UI changes are lost on restart."
  numExecutors: 2
  securityRealm:
    local:
      allowsSignup: false
      users:
        - id: admin
          password: "${JENKINS_ADMIN_PASSWORD}"
  authorizationStrategy:
    loggedInUsersCanDoAnything:
      allowAnonymousRead: false
  globalNodeProperties:
    - envVars:
        env:                                   # NON-secret config only
          - {key: HF_MODEL_REPO,     value: "${HF_MODEL_REPO}"}
          - {key: HF_SPACE_REPO,     value: "${HF_SPACE_REPO}"}
          - {key: MODEL_SERVICE_URL, value: "${MODEL_SERVICE_URL}"}
          - {key: MLFLOW_TRACKING_URI, value: "${MLFLOW_TRACKING_URI}"}
credentials:
  system:
    domainCredentials:
      - credentials:
          - usernamePassword: {scope: GLOBAL, id: github-readonly, username: "git", password: "${GITHUB_TOKEN}"}
          - usernamePassword: {scope: GLOBAL, id: dagshub, username: "${DAGSHUB_USER}", password: "${DAGSHUB_TOKEN}"}
          - string: {scope: GLOBAL, id: hf-token-write, secret: "${HF_TOKEN_WRITE}"}
          - string: {scope: GLOBAL, id: hf-token-read,  secret: "${HF_TOKEN_READ}"}
          - string: {scope: GLOBAL, id: postgres-password, secret: "${POSTGRES_PASSWORD}"}
          - string: {scope: GLOBAL, id: retrain-webhook-token, secret: "${RETRAIN_WEBHOOK_TOKEN}"}
          - usernamePassword: {scope: GLOBAL, id: smoke-user, username: "smoke", password: "${SMOKE_PASSWORD}"}
jobs:
  - script: >
      multibranchPipelineJob('triageiq') {
        branchSources { git { id('triageiq-repo'); remote('${GITHUB_REPO_URL}'); credentialsId('github-readonly') } }
        triggers { periodicFolderTrigger { interval('2m') } }
      }
  - script: >
      pipelineJob('triageiq-retrain') {
        definition { cpsScm {
          scm { git { remote { url('${GITHUB_REPO_URL}'); credentials('github-readonly') }; branch('*/main') } }
          scriptPath('Jenkinsfile.retrain'); lightweight(true)
        } }
      }
```
- Add `SMOKE_PASSWORD=<plain password of the "smoke" htpasswd user>` to `.env` (and to Part 0.8 through a PR).
- **Why polling instead of GitHub webhooks**: GitHub can't reach a Jenkins on your PC. The multibranch job scans the repo every 2 minutes. When Jenkins is public later (AWS), switch to a GitHub webhook. That's one JCasC change, and the pipelines stay the same.

**Compose service** (profile `ops`)
```yaml
  jenkins:
    build: {context: ., dockerfile: ops/jenkins/Dockerfile}
    image: triageiq-jenkins:local
    profiles: [ops]
    env_file: .env
    ports: ["127.0.0.1:8090:8080"]
    volumes:
      - jenkins_home:/var/jenkins_home
      - /var/run/docker.sock:/var/run/docker.sock     # the one allowed host mount (Part 0.5 rule 3)
    group_add: ["${DOCKER_SOCK_GID:-0}"]
    deploy: {resources: {limits: {memory: 2G}}}
    restart: unless-stopped
```
Find the socket's group ID:
```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock alpine stat -c %g /var/run/docker.sock
```
On Docker Desktop it is usually `0`. Put the number in `.env` as `DOCKER_SOCK_GID`.

**Risk you must state in the report**: access to the Docker socket gives root on the Docker host. That's acceptable on a single-user demo machine. On AWS, move builds to a separate build agent.
`# shortcut: builds run on the Jenkins controller with the host Docker socket, move to agents when Jenkins is shared or on AWS`

**Dry tests**
- `docker compose --env-file .env.example config -q`
- After it starts: the **Jenkinsfile linter**
  - create an API token for `admin` (user menu → Security), then:
    ```bash
    curl -s -u admin:<api-token> -F "jenkinsfile=<Jenkinsfile" http://127.0.0.1:8090/pipeline-model-converter/validate
    ```
  - B2 and later phases run this on every Jenkinsfile change, before pushing.

**Gate B1** (ticked by B-Infra)
- [ ] `docker compose --profile ops up -d --build jenkins` → log in as `admin`, no setup wizard
- [ ] Jobs `triageiq` and `triageiq-retrain` exist. All credentials from casc.yaml exist, with values masked
- [ ] `docker compose exec jenkins docker ps` lists the running containers (socket access works)
- [ ] `docker compose rm -sf jenkins && docker volume rm triageiq_jenkins_home && docker compose --profile ops up -d jenkins` → identical Jenkins comes back
- [ ] An anonymous browser session sees the login page only

---

## B2 — CI/CD pipeline (B-Delivery)

**Goal**: every push is linted, tested and built. Every merge to `main` is deployed to the demo machine and smoke-tested, with no human steps.

### B2.1 Three rules that prevent most Jenkins-in-Docker failures
1. **Run every tool inside a Docker agent** (`agent { docker { image '...'; reuseNode true } }`). **Never** run `docker run -v $WORKSPACE:...` yourself.
   - Jenkins itself runs in a container, so `$WORKSPACE` is a path inside the Jenkins volume, not on the host.
   - The `docker-workflow` plugin handles this automatically by sharing Jenkins' volumes with the agent container.
2. **Docker agents run as Jenkins' user (UID 1000), not root.** So `pip install` into the system Python fails. Always create a venv: `python -m venv /tmp/venv && . /tmp/venv/bin/activate`. Set `HOME=$WORKSPACE` so tools have somewhere to write.
3. **Pin every tool image tag** (`python:3.11-slim`, `aquasec/trivy:<x.y.z>`, …). An unpinned tag changes underneath you and breaks builds randomly.

### B2.2 Stages
Build the pipeline in this order. Each later phase adds its stages to it.

| # | Stage | Added in | Runs on |
|---|---|---|---|
| 1 | Secrets scan | B3 | every branch |
| 2 | Lint | B2 | every branch |
| 3 | Unit tests | B2 | every branch |
| 4 | SAST + dependency audit | B3 | every branch |
| 5 | Validate configs (dry tests) | B2, extended in B3–B7 | every branch |
| 6 | Fetch data (DVC) | B2 | every branch |
| 7 | Build images | B2 | every branch |
| 8 | Image scan | B3 | every branch |
| 9 | Integration tests | B2 | every branch |
| 10 | Deploy (local) | B2 | `main` only |
| 11 | Smoke test | B2 | `main` only |
| 12 | Deploy model-service to HF | B2, after A3 | `main` + model-service changed |

### B2.3 `Jenkinsfile` skeleton
Stages marked `// B3` / `// B5` / … are added in those phases.
```groovy
pipeline {
  agent any
  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
    timeout(time: 60, unit: 'MINUTES')
  }
  environment {
    IMAGE_TAG = "${env.GIT_COMMIT.substring(0, 7)}"
    CI_NET    = "ci-${env.BUILD_NUMBER}-${env.GIT_COMMIT.substring(0, 7)}"
    HOME      = "${env.WORKSPACE}"
  }
  stages {
    // stage('Secrets scan')  — B3

    stage('Lint') {
      agent { docker { image 'python:3.11-slim'; reuseNode true } }
      steps {
        sh '''
          python -m venv /tmp/venv && . /tmp/venv/bin/activate
          pip install -q "ruff==<pin>"
          ruff check . && ruff format --check .
        '''
      }
    }

    stage('Unit tests') {
      agent { docker { image 'python:3.11-slim'; reuseNode true } }
      steps {
        sh '''
          for d in services/backend-api services/feedback-service services/ticket-generator services/model-service ml; do
            n=$(basename "$d")
            python -m venv "/tmp/venv-$n" && . "/tmp/venv-$n/bin/activate"
            pip install -q -r "$d/requirements.txt" -r "$d/requirements-dev.txt"
            (cd "$d" && pytest -q -m "not integration")
            deactivate
          done
        '''
      }
    }

    // stage('SAST + dependency audit') — B3

    stage('Validate configs') {
      parallel {
        stage('compose') { steps { sh 'docker compose --env-file .env.example config -q' } }
        // trivy config — B3 ; terraform — B5 ; kubeconform — B6 ; promtool/amtool/alloy — B7
      }
    }

    stage('Fetch data') {
      agent { docker { image 'python:3.11'; reuseNode true } }      // full image: DVC needs git
      steps {
        withCredentials([usernamePassword(credentialsId: 'dagshub', usernameVariable: 'DVC_USER', passwordVariable: 'DVC_PASS')]) {
          sh '''
            python -m venv /tmp/dvc && . /tmp/dvc/bin/activate && pip install -q "dvc==<pin>"
            dvc remote modify origin --local auth basic
            dvc remote modify origin --local user "$DVC_USER"
            dvc remote modify origin --local password "$DVC_PASS"
            dvc pull data/processed
          '''
        }
      }
    }

    stage('Build images') {
      steps {
        sh '''
          docker compose --env-file .env.example --profile local-model build
          docker build -f ml/Dockerfile -t triageiq-ml:$IMAGE_TAG -t triageiq-ml:latest .
          # gateway config test: fake upstream hosts so nginx -t can resolve them outside compose
          docker run --rm --add-host backend-api:127.0.0.1 --add-host feedback-service:127.0.0.1 \
            -e GATEWAY_HTPASSWD='ci:x' --entrypoint sh triageiq-gateway:$IMAGE_TAG \
            -c 'printf "%b\\n" "$GATEWAY_HTPASSWD" > /tmp/htpasswd && /docker-entrypoint.sh nginx -t'
        '''
      }
    }

    // stage('Image scan') — B3

    stage('Integration tests') {
      steps {
        sh '''
          docker network create "$CI_NET"
          docker run -d --name "pg-$CI_NET" --network "$CI_NET" \
            -e POSTGRES_USER=triageiq -e POSTGRES_DB=triageiq -e POSTGRES_PASSWORD=ci triageiq-postgres:$IMAGE_TAG
          # TCP check: during init Postgres listens only on a local socket, so this passes only when it's truly up
          for i in $(seq 1 45); do docker exec "pg-$CI_NET" pg_isready -h 127.0.0.1 -U triageiq && break; sleep 2; done
        '''
        script {
          docker.image('python:3.11-slim').inside("--network ${env.CI_NET}") {
            sh '''
              export DATABASE_URL="postgresql://triageiq:ci@pg-$CI_NET:5432/triageiq"
              for d in services/backend-api services/feedback-service ml; do
                n=$(basename "$d")
                python -m venv "/tmp/ivenv-$n" && . "/tmp/ivenv-$n/bin/activate"
                pip install -q -r "$d/requirements.txt" -r "$d/requirements-dev.txt"
                (cd "$d" && pytest -q -m integration)
                deactivate
              done
            '''
          }
        }
      }
      post { always { sh 'docker rm -f "pg-$CI_NET" || true; docker network rm "$CI_NET" || true' } }
    }

    stage('Deploy (local)') {
      when { branch 'main' }
      steps {
        // shortcut: secrets reach compose via the Jenkins container's env (from .env), move to withCredentials per variable on AWS
        sh 'docker compose up -d'            // default profile only: app services. Never touches jenkins/monitoring
      }
    }

    stage('Smoke test') {
      when { branch 'main' }
      steps {
        withCredentials([usernamePassword(credentialsId: 'smoke-user', usernameVariable: 'SMOKE_USER', passwordVariable: 'SMOKE_PASSWORD')]) {
          sh 'GATEWAY_URL=http://gateway:8080 python3 scripts/smoke_test.py'
        }
      }
    }

    stage('Deploy model-service to HF') {
      when { allOf { branch 'main'; changeset 'services/model-service/**' } }
      agent { docker { image "triageiq-ml:${env.IMAGE_TAG}"; reuseNode true } }
      steps {
        withCredentials([string(credentialsId: 'hf-token-write', variable: 'HF_TOKEN_WRITE')]) {
          sh 'python -m triage_ml.deploy_space'
        }
      }
    }
  }
  post { always { cleanWs() } }
}
```

**Notes**
- **How deploy works locally**: Jenkins runs `docker compose up -d` against the **host's** Docker, using the same project name (`name: triageiq` in the compose file) as the stack the team started by hand. So it replaces those containers with the new `IMAGE_TAG` images.
- That works only because Part 0.5 rule 3 bans bind mounts. A bind mount would point at a path inside Jenkins' volume that the host doesn't have.
- `http://gateway:8080` resolves from Jenkins because Jenkins is in the same compose project, so it's on the same network (`triageiq_default`).
- Until Team A's real services exist, these stages run against the Phase 0 stubs. That's the point: the pipeline is ready before the code is.
- `# shortcut: every service's tests run on every build (no path filters); add changeset filters if builds exceed ~15 min`

**Dry tests**: the Jenkinsfile linter (B1) before every push, plus a pipeline run on a feature branch (deploy stages are skipped on non-`main` branches).

**Gate B2** (ticked by B-Infra)
- [ ] A push to a `b/...` branch starts a build within ~2 minutes, and stages 2, 3, 5, 6, 7 and 9 are green on the stubs
- [ ] Merging to `main` runs deploy + smoke. `docker compose ps` shows the new `IMAGE_TAG` on the app services
- [ ] A deliberately failing unit test on a branch makes the build red at **Unit tests**, and nothing gets deployed
- [ ] The build leaves no `ci-*` networks or `pg-ci-*` containers behind (`docker network ls`, `docker ps -a`)

---

## B3 — DevSecOps (B-Delivery)

**Goal**: secrets, insecure code, vulnerable dependencies, misconfiguration and vulnerable images are all caught automatically, and the build fails before anything is deployed.

### B3.1 Pipeline stages to add
```groovy
stage('Secrets scan') {
  agent { docker { image 'zricethezav/gitleaks:<pin>'; args '--entrypoint='; reuseNode true } }
  steps { sh 'gitleaks git --redact --no-banner .' }      // v8.19+ syntax; older pins: gitleaks detect --source . --redact
}

stage('SAST + dependency audit') {
  agent { docker { image 'python:3.11-slim'; reuseNode true } }
  steps {
    sh '''
      python -m venv /tmp/sec && . /tmp/sec/bin/activate
      pip install -q "bandit==<pin>" "pip-audit==<pin>"
      bandit -r services ml -x "*/tests/*" -ll -ii           # medium+ severity and confidence fail the build
      for r in services/*/requirements.txt ml/requirements.txt; do pip-audit -r "$r"; done
    '''
  }
}

// inside 'Validate configs' parallel:
stage('trivy config') {
  agent { docker { image 'aquasec/trivy:<pin>'; args '--entrypoint='; reuseNode true } }
  steps { sh 'trivy config --exit-code 1 --severity HIGH,CRITICAL --cache-dir /tmp/trivy .' }   // Dockerfiles, Terraform, K8s YAML
}

stage('Image scan') {
  agent { docker { image 'aquasec/trivy:<pin>'; args '--entrypoint= -v /var/run/docker.sock:/var/run/docker.sock'; reuseNode true } }
  steps {
    sh '''
      for s in gateway backend-api feedback-service ticket-generator postgres model-service; do
        trivy image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed --cache-dir /tmp/trivy "triageiq-$s:$IMAGE_TAG"
      done
    '''
  }
}
```
- The socket mount in `Image scan` is safe to pass as a path: the socket has the same path on the host and inside Jenkins. Only *workspace* paths differ.
- `# shortcut: Trivy re-downloads its vulnerability DB every build, add a cache volume if the stage exceeds ~2 min`

### B3.2 Accepted risks
- A finding you decide to accept goes in `.trivyignore` (or `# nosec B<id>` for Bandit), **with a comment on the line above saying why and who accepted it**. Example: `# CVE-XXXX: in torch, not reachable from our code (accepted: <name>, <date>)`.
- Silent ignores are rejected in review.

### B3.3 Local guardrails (`.pre-commit-config.yaml`)
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: <pin>
    hooks: [{id: ruff}, {id: ruff-format}]
  - repo: https://github.com/gitleaks/gitleaks
    rev: <pin>
    hooks: [{id: gitleaks}]
```
Every developer runs `pip install pre-commit && pre-commit install` once. A leaked token is then blocked **before** it is committed. Jenkins is the second line of defence.

### B3.4 Hardening checklist (review all of Team A's work against it; open issues for gaps)
- [ ] Every **app** image runs as non-root (UID 1000; gateway UID 101 via the unprivileged nginx image)
- [ ] App services in compose have `read_only: true`, `tmpfs` only where needed, `cap_drop: [ALL]`, `no-new-privileges`, and a memory limit
- [ ] Only `gateway` publishes a port, and only on `127.0.0.1`. Admin UIs only on `127.0.0.1`. Postgres never published
- [ ] No secret in any Dockerfile, image layer (`docker history --no-trunc`), compose file or repo file
- [ ] `/metrics` isn't reachable through the gateway (returns 404)
- [ ] `X-Reviewer` can't be spoofed through the gateway
- [ ] Tokens are least-privilege (Part 0.12): read vs write HF tokens, a read-only GitHub token
- [ ] The frontend renders ticket text with `textContent` only

### B3.5 Prove the gates work (keep the evidence for the report)
On a throwaway branch `b/b3-security-demo` (**never merge it**), make three separate commits, each of which must fail at the named stage:
1. A file containing a realistic-looking but fake AWS key (`AKIA` + 16 uppercase letters/digits) → **Secrets scan**. Revert it.
2. `requests==2.19.0` added to one requirements file → **SAST + dependency audit** (pip-audit). Revert it.
3. A query built with an f-string in a `db.py` → **SAST** (Bandit B608). Revert it.

Take screenshots of the three red builds. Delete the branch afterwards.

**Gate B3** (ticked by B-Infra)
- [ ] `main` is green with all security stages in place
- [ ] The three demo failures happened at the right stages (screenshots in `docs/evidence/` or in the PR)
- [ ] The hardening checklist is fully ticked, or each gap has an issue assigned to Team A
- [ ] `pre-commit run --all-files` passes

---

## B4 — Public access (B-Infra)

**Goal**: anyone with a reviewer login can use the app from the internet over HTTPS. **No router port-forwarding, no inbound firewall holes**: Cloudflare Tunnel makes an *outbound* connection from the PC.

**Two compose services**
```yaml
  tunnel-quick:                                   # POC: no account, no domain, random URL each start
    image: cloudflare/cloudflared:<pin>
    command: ["tunnel", "--no-autoupdate", "--url", "http://gateway:8080"]
    profiles: [public-quick]
    depends_on: {gateway: {condition: service_healthy}}
    restart: unless-stopped

  tunnel:                                         # named tunnel from B5 Terraform: fixed hostname on your domain
    image: cloudflare/cloudflared:<pin>
    command: ["tunnel", "--no-autoupdate", "run"]
    environment: {TUNNEL_TOKEN: "${TUNNEL_TOKEN}"}
    profiles: [public]
    depends_on: {gateway: {condition: service_healthy}}
    restart: unless-stopped
```
- **Quick tunnel**: `docker compose --profile public-quick up -d tunnel-quick`, then `docker compose logs tunnel-quick | grep trycloudflare.com` to get the URL.
- Cloudflare says quick tunnels are for testing (no uptime guarantee, and the URL changes every restart). Fine for the POC demo.
- **Named tunnel** (needs a domain on a free Cloudflare account): created by Terraform in B5. Put the token in `.env` as `TUNNEL_TOKEN` and use profile `public`.

**Security when public** (all of it is already in Team A's gateway; verify it)
- HTTPS is terminated by Cloudflare. Basic auth protects everything except `/healthz`.
- The rate limit is per **real client IP**. The gateway reads `CF-Connecting-IP` only from the Docker-network address of `cloudflared` (`set_real_ip_from` in A6). Without that, every user would share one rate-limit bucket.
- Only the gateway is exposed. Jenkins, Grafana, Prometheus and Alertmanager are **never** put behind the tunnel.

**Dry tests**: `docker compose --env-file .env.example --profile public --profile public-quick config -q`

**Gate B4** (ticked by B-Delivery)
- [ ] On a phone using **mobile data** (not your WiFi), the tunnel URL shows the login prompt. After login, the review page works end to end
- [ ] Without a login, `curl https://<tunnel-url>/api/labels` → 401. `curl https://<tunnel-url>/healthz` → `ok`
- [ ] `curl https://<tunnel-url>/api/metrics` → 404
- [ ] Stopping the tunnel container makes the URL stop working (nothing else is exposed)

---

## B5 — Infrastructure as Code (B-Infra)

**Goal**: the AWS environment and the named Cloudflare tunnel exist **as code**. They're validated on every build. Optionally apply once to prove it works, then destroy.

### B5.1 AWS (`infra/aws/`)
**Design**: one EC2 instance runs the **same compose stack** (all profiles), which keeps "no code changes" true.
- **No inbound ports at all.** Public access goes through the named Cloudflare tunnel (outbound), and admin shell access goes through **SSM Session Manager**. SSH is an optional variable, off by default.

| File | Contents |
|---|---|
| `versions.tf` | `terraform { required_version = ">= 1.6" }`; providers `aws` (pin the current major from the Terraform Registry). **Local state** (see the shortcut below) |
| `variables.tf` | `region` (default `ap-south-1`), `instance_type` (default `t3.large`: 8 GB, measured need ≈ 4–5 GB), `root_volume_gb` (40), `git_repo_url`, `git_ref` (tag/branch), `dotenv_param_name` (default `/triageiq/dotenv`), `admin_ssh_cidr` (default `""` = no SSH rule) |
| `main.tf` | default VPC + subnets (data sources); Ubuntu 24.04 AMI (data source, owner `099720109477`); security group with **no ingress** (+ SSH only if `admin_ssh_cidr != ""`), all egress; IAM role + instance profile with `AmazonSSMManagedInstanceCore` + an inline policy allowing `ssm:GetParameter` on `arn:aws:ssm:<region>:<account>:parameter/triageiq/*`; `aws_instance` with `metadata_options { http_tokens = "required" }` (IMDSv2), encrypted gp3 root volume, `user_data = templatefile("cloud-init.yaml.tftpl", {...})` |
| `outputs.tf` | `instance_id`, the `aws ssm start-session --target <id>` command |
| `cloud-init.yaml.tftpl` | bootstrap, below |

**`cloud-init.yaml.tftpl` outline**
- In a Terraform template, a literal `${` must be written `$${`. Shell `$VAR` without braces is fine.

```yaml
#cloud-config
package_update: true
packages: [ca-certificates, curl, git, gnupg]
runcmd:
  # 1. Docker Engine + compose plugin: same official apt repo steps as ops/jenkins/Dockerfile
  - <docker apt repo install commands>
  - snap install aws-cli --classic
  # 2. secrets: the whole .env lives in ONE SecureString SSM parameter (created by hand, never in Terraform state)
  - aws ssm get-parameter --region ${region} --name ${dotenv_param_name} --with-decryption --query Parameter.Value --output text > /root/triageiq.env
  - chmod 600 /root/triageiq.env
  # 3. code at the requested ref
  - sh -c 'set -a; . /root/triageiq.env; set +a; git clone --branch ${git_ref} "https://x-access-token:$GITHUB_TOKEN@$(echo ${git_repo_url} | sed s#https://##)" /opt/triageiq'
  - mv /root/triageiq.env /opt/triageiq/.env
  # 4. data for the generator image (host shell, so this bind mount is fine)
  - cd /opt/triageiq && docker run --rm -v /opt/triageiq:/repo -w /repo --env-file .env python:3.11 sh -c 'pip install -q dvc && dvc remote modify origin --local auth basic && dvc remote modify origin --local user "$DAGSHUB_USER" && dvc remote modify origin --local password "$DAGSHUB_TOKEN" && dvc pull data/processed'
  # 5. start everything (identical to the PC)
  - cd /opt/triageiq && docker compose --profile ops --profile monitoring --profile public up -d --build
```

**One-time manual prep** (documented, not in Terraform, because secrets in Terraform end up in plain text in the state file):
- `aws ssm put-parameter --name /triageiq/dotenv --type SecureString --value file://.env.aws`
- `.env.aws` = your `.env` with `DOCKER_SOCK_GID` set to the host's `docker` group ID (`getent group docker | cut -d: -f3` on Ubuntu), plus a `TUNNEL_TOKEN`.
- If `get-parameter` fails with a KMS AccessDenied, add `kms:Decrypt` on the `alias/aws/ssm` key to the inline policy.

`# shortcut: local Terraform state, single operator only; move to an S3 backend with locking before a second person runs apply`

### B5.2 Cloudflare named tunnel (`infra/cloudflare/`)
- **Needs**: a domain on a free Cloudflare account, and an API token scoped to *Account › Cloudflare Tunnel: Edit* + *Zone › DNS: Edit*, given as env `CLOUDFLARE_API_TOKEN`.
- **Variables**: `account_id`, `zone_id`, `hostname` (e.g. `triageiq.<your-domain>`).
- **Resources** (names are for provider **v5**; v4 used `cloudflare_tunnel`, `cloudflare_tunnel_config`, `cloudflare_record`. Pin one major version and follow *its* docs):
  - `random_password` (≥ 32 chars) → base64 → the tunnel secret
  - `cloudflare_zero_trust_tunnel_cloudflared` (remotely managed config)
  - `cloudflare_zero_trust_tunnel_cloudflared_config`: ingress `hostname → http://gateway:8080`, then a catch-all `http_status:404`
  - `cloudflare_dns_record`: CNAME `hostname → <tunnel_id>.cfargotunnel.com`, proxied
  - **Output** the tunnel token (`sensitive = true`) → `.env` `TUNNEL_TOKEN`
- **Optional later**: a Cloudflare Access application (email one-time PIN) in front of the hostname, so basic auth becomes a second layer.

The same tunnel works from the PC and from EC2. Only the machine running `cloudflared` changes.

### B5.3 Dry tests (added to `Validate configs`)
```groovy
stage('terraform') {
  agent { docker { image 'hashicorp/terraform:<pin>'; args '--entrypoint='; reuseNode true } }
  steps {
    sh '''
      terraform fmt -check -recursive infra
      for d in infra/aws infra/cloudflare; do
        terraform -chdir=$d init -backend=false -input=false && terraform -chdir=$d validate
      done
    '''
  }
}
```
`trivy config` (B3) already scans `infra/` for misconfigurations: public S3, missing IMDSv2, open security groups and so on.

**`terraform plan`** needs real credentials, so it isn't run in CI. Run it by hand with a **read-only** IAM user and attach the output to the PR.

**Cost of an optional real test** (on-demand prices, check your region): `t3.large` ≈ $0.09/hour. Apply → open the tunnel URL → run the smoke test → destroy. **Under $1 for an afternoon.** Always finish with `terraform destroy` and confirm in the EC2 console.

**Gate B5** (ticked by B-Delivery)
- [ ] `fmt`, `validate` and `trivy config` are green in Jenkins
- [ ] `terraform plan` for `infra/aws` shows exactly: 1 instance, 1 security group (no ingress), 1 IAM role + profile + policy. The output is attached to the PR
- [ ] `terraform plan` for `infra/cloudflare` shows the tunnel, its config and the DNS record (if a domain is available)
- [ ] *(Optional, recommended once before the final demo)*: apply → stack healthy → smoke test via the tunnel hostname → `terraform destroy` → console confirms nothing is left

---

## B6 — Kubernetes on kind (B-Infra)

**Why this exists**: Kubernetes is on the DevOps requirement list. The app doesn't *need* it at this scale, but the same images run on a local kind cluster to show the skill. **If your instructor waives Kubernetes, delete this phase**: nothing else depends on it.

**Files**: `deploy/kind/cluster.yaml`, `deploy/k8s/00-namespace.yaml … 50-gateway.yaml`, `deploy/k8s/README.md` (the commands below).

**`deploy/kind/cluster.yaml`**
```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - {containerPort: 30080, hostPort: 8081, listenAddress: "127.0.0.1"}
```

**Manifests** (plain YAML, namespace `triageiq`, no kustomize, no Helm)
| File | Objects |
|---|---|
| `00-namespace.yaml` | Namespace |
| `10-postgres.yaml` | StatefulSet (1 replica, `volumeClaimTemplates` 1Gi, env from Secret), Service `postgres` (ClusterIP 5432), readiness `exec pg_isready -h 127.0.0.1 -U triageiq` |
| `20-backend-api.yaml` | Deployment + Service `backend-api` (ClusterIP 8000) |
| `30-feedback-service.yaml` | Deployment + Service `feedback-service` (ClusterIP 8000) |
| `40-ticket-generator.yaml` | Deployment (1 replica), `emptyDir` at `/state` |
| `50-gateway.yaml` | Deployment + Service `gateway` (**NodePort 30080** → 8080) |

The model stays on the HF Space (`MODEL_SERVICE_URL` comes from the Secret). We use NodePort rather than an Ingress controller: one fewer component, and enough for one entry point.

**Every Deployment uses the same pattern**
```yaml
spec:
  replicas: 1
  template:
    spec:
      securityContext: {runAsNonRoot: true, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: backend-api
          image: triageiq-backend-api:dev              # loaded into kind, never pulled
          imagePullPolicy: IfNotPresent
          envFrom: [{secretRef: {name: triageiq-env}}]
          env:
            - {name: DATABASE_URL, value: "postgresql://triageiq:$(POSTGRES_PASSWORD)@postgres:5432/triageiq"}
          ports: [{containerPort: 8000}]
          readinessProbe: {httpGet: {path: /health, port: 8000}, periodSeconds: 10}
          livenessProbe:  {httpGet: {path: /health, port: 8000}, initialDelaySeconds: 20, periodSeconds: 20}
          resources:
            requests: {cpu: 50m,  memory: <A8 observed peak>}
            limits:   {cpu: 500m, memory: <A8 limit>}
          securityContext: {readOnlyRootFilesystem: true, allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
          volumeMounts: [{name: tmp, mountPath: /tmp}]
      volumes: [{name: tmp, emptyDir: {}}]
```
- **How to pick resources** (this is what graders ask about):
  - `requests.memory` = the steady-state peak Team A measured in A8. The scheduler reserves this.
  - `limits.memory` = A8's limit (2 × peak). Above it the pod is OOM-killed, so a runaway pod can't starve the others.
  - CPU: a small request (these services are I/O-bound and wait on the model or the DB), and a limit of 0.5 core.
- `$(POSTGRES_PASSWORD)` is expanded by Kubernetes from the Secret loaded through `envFrom`.

**Deploy** (from Git Bash on the demo machine)
```bash
kind create cluster --name triageiq --config deploy/kind/cluster.yaml
docker compose build                                   # images tagged :dev
for s in gateway backend-api feedback-service ticket-generator postgres; do
  kind load docker-image "triageiq-$s:dev" --name triageiq
done
kubectl apply -f deploy/k8s/00-namespace.yaml
# kubectl does NOT strip quotes from env files: remove the quotes around GATEWAY_HTPASSWD first
sed "s/^\(GATEWAY_HTPASSWD=\)'\(.*\)'$/\1\2/" .env > deploy/k8s/.env.k8s     # gitignored
kubectl -n triageiq create secret generic triageiq-env --from-env-file=deploy/k8s/.env.k8s --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f deploy/k8s/
kubectl -n triageiq rollout status deploy/gateway --timeout=180s
GATEWAY_URL=http://127.0.0.1:8081 SMOKE_USER=smoke SMOKE_PASSWORD=... python scripts/smoke_test.py
```
- `# shortcut: generator cursor on emptyDir, a pod restart resends from the start; use a PVC if the kind stack runs for long`
- **Stretch** (CD into Kubernetes from Jenkins):
  1. Add `kubectl` to the Jenkins image.
  2. `docker network connect kind <jenkins container>`.
  3. Store `kind get kubeconfig --internal --name triageiq` as a secret-file credential.
  4. Add a `main`-only stage that runs `kind load` + `kubectl set image`.

**Dry tests** (added to `Validate configs`)
```groovy
stage('kubeconform') {
  agent { docker { image 'ghcr.io/yannh/kubeconform:<pin>'; args '--entrypoint='; reuseNode true } }
  steps { sh '/kubeconform -strict -summary deploy/k8s/' }
}
```
Plus, by hand against the kind cluster: `kubectl apply --dry-run=server -f deploy/k8s/`.

**Gate B6** (ticked by B-Delivery)
- [ ] kubeconform is green in Jenkins
- [ ] All pods `Running`/`Ready`. The smoke test passes against `127.0.0.1:8081`
- [ ] `kubectl -n triageiq delete pod -l app=backend-api` → a new pod comes up by itself, and the smoke test passes again (self-healing)
- [ ] `kubectl -n triageiq get pod -o jsonpath='{..securityContext}'` shows non-root and read-only settings

### ══ DevOps POC gate ══
Run the checklist in Part 0.2.2 with all four people. Record a 5-minute walkthrough video.

---

## B7 — Monitoring and logging as code (B-Infra, MLOps phase)

**Goal**:
- Prometheus collects the metrics in Part 0.10.
- An alert rule (unit-tested) decides when the model needs retraining.
- Alertmanager routes that alert to Jenkins.
- Grafana shows business and technical dashboards.
- Loki holds every service's logs, searchable by `request_id`.

Everything uses profile `monitoring`, images are built from `ops/*` (config baked in), state is in named volumes, and UIs are on `127.0.0.1` only.

### B7.1 Prometheus (`ops/prometheus/`)
- **`Dockerfile`**: `FROM prom/prometheus:<pin>`, then `COPY ops/prometheus/prometheus.yml ops/prometheus/alerts.yml /etc/prometheus/`.
- **Compose**: command `["--config.file=/etc/prometheus/prometheus.yml","--storage.tsdb.path=/prometheus","--storage.tsdb.retention.time=15d"]`, volume `prometheus_data:/prometheus`, port `127.0.0.1:9090:9090`.
- **Why a named volume matters**: Prometheus keeps all metric history in that directory. Without the volume, every restart wipes it.

**`prometheus.yml`**
```yaml
global: {scrape_interval: 15s, evaluation_interval: 30s}
rule_files: [/etc/prometheus/alerts.yml]
alerting:
  alertmanagers: [{static_configs: [{targets: ["alertmanager:9093"]}]}]
scrape_configs:
  - {job_name: backend-api,      static_configs: [{targets: ["backend-api:8000"]}]}
  - {job_name: feedback-service, static_configs: [{targets: ["feedback-service:8000"]}]}
  - {job_name: prometheus,       static_configs: [{targets: ["localhost:9090"]}]}
```
The model-service isn't scraped: it runs on HF. Its latency and errors are measured from the backend side (`triageiq_model_call_*`).

**`alerts.yml`**
```yaml
groups:
  - name: triageiq-model-quality
    rules:
      - record: triageiq:feedback_error_ratio_1h
        expr: |
          sum by (model_version) (increase(triageiq_feedback_incorrect_total[1h]))
          /
          sum by (model_version) (increase(triageiq_feedback_total[1h]))
      - record: triageiq:feedback_count_1h
        expr: sum by (model_version) (increase(triageiq_feedback_total[1h]))
      - alert: ModelErrorRateHigh
        expr: triageiq:feedback_error_ratio_1h > 0.45 and triageiq:feedback_count_1h >= 30
        for: 5m
        labels: {severity: retrain}
        annotations:
          summary: "Model {{ $labels.model_version }} error ratio {{ $value | humanizePercentage }} over the last hour"
```
- **Per `model_version`**: after a new model is promoted, it starts with zero feedback, so the alert can't fire again until reviewers have judged ≥ 30 of *its* predictions. This stops the loop of "alert fires again for the old model's errors."
- **`>= 30`**: a human produces few verdicts per minute. A ratio from 6 verdicts is noise.
- **Setting the threshold** (replace `0.45`):
  1. Take Team A's **golden accuracy** from `data/README.md` (A2).
  2. `threshold = round((1 − accuracy) + 0.15, 2)`.
  3. For example, accuracy 0.70 → 0.45.
- **Check that the drift demo will trigger it**: with drift ratio `r`, the error becomes `(1 − r)·e + r`, where `e = 1 − accuracy`. It crosses the threshold when `r > 0.15 / (1 − e)`. With `e = 0.30` that needs `r > 0.22`, so the default `DRIFT_RATIO=0.4` is safe.

**`alerts_test.yml`**: unit tests for the rule, the most important dry test of the MLOps loop
```yaml
rule_files: [alerts.yml]
evaluation_interval: 1m
tests:
  - name: fires when many verdicts and high error
    interval: 1m
    input_series:
      - {series: 'triageiq_feedback_total{model_version="abc"}',           values: '0+1x90'}     # 60/h
      - {series: 'triageiq_feedback_incorrect_total{model_version="abc"}', values: '0+0.6x90'}   # 60% wrong
    alert_rule_test:
      - eval_time: 75m
        alertname: ModelErrorRateHigh
        exp_alerts: [{exp_labels: {severity: retrain, model_version: abc}}]
  - name: silent when too few verdicts
    interval: 1m
    input_series:
      - {series: 'triageiq_feedback_total{model_version="abc"}',           values: '0+0.3x90'}   # ~18/h
      - {series: 'triageiq_feedback_incorrect_total{model_version="abc"}', values: '0+0.3x90'}   # 100% wrong
    alert_rule_test:
      - {eval_time: 75m, alertname: ModelErrorRateHigh, exp_alerts: []}
  - name: silent when error is normal
    interval: 1m
    input_series:
      - {series: 'triageiq_feedback_total{model_version="abc"}',           values: '0+1x90'}
      - {series: 'triageiq_feedback_incorrect_total{model_version="abc"}', values: '0+0.3x90'}   # 30% wrong
    alert_rule_test:
      - {eval_time: 75m, alertname: ModelErrorRateHigh, exp_alerts: []}
```

### B7.2 Alertmanager (`ops/alertmanager/`)
**`alertmanager.yml`**
```yaml
route:
  receiver: "null"
  group_by: [alertname]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 6h            # longer than any retrain; Jenkins also refuses overlaps
  routes:
    - matchers: ['severity="retrain"']
      receiver: jenkins-retrain
receivers:
  - name: "null"
  - name: jenkins-retrain
    webhook_configs:
      - url_file: /tmp/secrets/jenkins_webhook_url
        send_resolved: false     # CRITICAL: otherwise the "resolved" notification also triggers a retrain
```

**`entrypoint.sh`**: the webhook URL contains a secret token, so it's written at start from env instead of being baked into the image
```sh
#!/bin/sh
set -eu
mkdir -p /tmp/secrets
printf '%s' "http://jenkins:8080/generic-webhook-trigger/invoke?token=${RETRAIN_WEBHOOK_TOKEN}" > /tmp/secrets/jenkins_webhook_url
exec /bin/alertmanager --config.file=/etc/alertmanager/alertmanager.yml --storage.path=/alertmanager
```
- **Dockerfile**: `FROM prom/alertmanager:<pin>`, `COPY` both files, `ENTRYPOINT ["/bin/sh","/etc/alertmanager/entrypoint.sh"]`.
- **Compose**: env `RETRAIN_WEBHOOK_TOKEN`, port `127.0.0.1:9093:9093`.
- If your pinned version rejects `url_file`, `amtool check-config` will say so. Upgrade the pin rather than baking the token in.

### B7.3 Grafana (`ops/grafana/`)
- **Dockerfile**:
  - `FROM grafana/grafana:<pin>`
  - `COPY ops/grafana/provisioning /etc/grafana/provisioning`
  - `COPY ops/grafana/dashboards /etc/grafana/dashboards`
  - Use `/etc/grafana/dashboards`, **not** `/var/lib/grafana/...`: that path is the data volume, and the volume would hide newer dashboard files.
- **Compose**:
  - env `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}`, `GF_USERS_ALLOW_SIGN_UP=false`, `GF_AUTH_ANONYMOUS_ENABLED=false`
  - volume `grafana_data:/var/lib/grafana`
  - port `127.0.0.1:3000:3000`
- **`provisioning/datasources/datasources.yaml`**
  ```yaml
  apiVersion: 1
  datasources:
    - {name: Prometheus, uid: prometheus, type: prometheus, access: proxy, url: http://prometheus:9090, isDefault: true}
    - {name: Loki,       uid: loki,       type: loki,       access: proxy, url: http://loki:3100}
  ```
- **`provisioning/dashboards/dashboards.yaml`**
  ```yaml
  apiVersion: 1
  providers:
    - {name: triageiq, folder: TriageIQ, type: file, allowUiUpdates: false, options: {path: /etc/grafana/dashboards}}
  ```
- **Dashboard workflow**: build it in the UI → *Export → Save to file* → commit as `ops/grafana/dashboards/triageiq-overview.json` → rebuild the image. UI edits aren't saved (`allowUiUpdates: false`), which keeps the dashboards in git.

**Dashboard `TriageIQ Overview`: panels and queries**
| Row | Panel | Query |
|---|---|---|
| Business | Tickets / min | `sum(rate(triageiq_predictions_total[5m])) * 60` |
| Business | Live model accuracy (1h) by version | `1 - triageiq:feedback_error_ratio_1h` |
| Business | Error ratio (1h) by version, **with a threshold line** at the alert value | `triageiq:feedback_error_ratio_1h` |
| Business | Verdicts in last hour by version | `triageiq:feedback_count_1h` |
| Business | Predicted queue mix (stacked) | `sum by (label) (rate(triageiq_predictions_total[15m]))` |
| Model | Version currently serving | `count by (model_version) (rate(triageiq_predictions_total[5m]) > 0)` |
| Model | Model call latency p50 / p95 | `histogram_quantile(0.95, sum by (le) (rate(triageiq_model_call_seconds_bucket[5m])))` (and 0.5) |
| Model | Model call errors by reason | `sum by (reason) (rate(triageiq_model_call_errors_total[5m]))` |
| Ops | Retrain alert state | `ALERTS{alertname="ModelErrorRateHigh"}` |
| Ops | Scrape targets up | `up` |
| Logs | Errors (Loki) | `{service=~"backend-api\|feedback-service\|ticket-generator"} \| json \| level="ERROR"` |

The "queue mix" panel is the **label-free drift signal**: when the held-out queue starts arriving, the mix shifts before any reviewer has said a word.

### B7.4 Logs: Loki + Alloy
- **Loki**: `grafana/loki:<pin>` with the image's built-in single-node config. Volume `loki_data:/loki`. No published port (only Grafana talks to it).
  `# shortcut: no log retention limit, enable the compactor retention settings if the volume grows past a few GB`
- **Alloy** (collects container stdout from the Docker socket; it replaces the retired Promtail): `FROM grafana/alloy:<pin>`, `COPY ops/alloy/config.alloy /etc/alloy/config.alloy`, command `["run","/etc/alloy/config.alloy","--storage.path=/var/lib/alloy/data"]`, mount `/var/run/docker.sock` (an allowed exception).
- **`ops/alloy/config.alloy`**: check component names against the docs for your pinned version.
  ```
  discovery.docker "containers" { host = "unix:///var/run/docker.sock" }

  discovery.relabel "containers" {
    targets = discovery.docker.containers.targets
    rule {
      source_labels = ["__meta_docker_container_label_com_docker_compose_service"]
      target_label  = "service"
    }
  }

  loki.source.docker "containers" {
    host       = "unix:///var/run/docker.sock"
    targets    = discovery.relabel.containers.output
    forward_to = [loki.process.json.receiver]
  }

  loki.process "json" {
    stage.json   { expressions = { level = "level" } }
    stage.labels { values = { level = "" } }
    forward_to = [loki.write.local.receiver]
  }

  loki.write "local" { endpoint { url = "http://loki:3100/loki/api/v1/push" } }
  ```
- Keep `request_id` **out of labels**. It's unique per request and would blow up Loki's index. Search for it with a filter instead: `{service="backend-api"} |= "<request-id>"`.

### B7.5 Dry tests (added to `Validate configs`)
```groovy
stage('promtool') {
  agent { docker { image 'prom/prometheus:<pin>'; args '--entrypoint='; reuseNode true } }
  steps { sh 'cd ops/prometheus && promtool check config prometheus.yml && promtool check rules alerts.yml && promtool test rules alerts_test.yml' }
}
stage('amtool') {
  agent { docker { image 'prom/alertmanager:<pin>'; args '--entrypoint='; reuseNode true } }
  steps { sh '''
    amtool check-config ops/alertmanager/alertmanager.yml
    amtool config routes test --config.file=ops/alertmanager/alertmanager.yml severity=retrain | grep -q jenkins-retrain
  ''' }
}
stage('alloy') {
  agent { docker { image 'grafana/alloy:<pin>'; args '--entrypoint='; reuseNode true } }
  steps { sh 'alloy fmt ops/alloy/config.alloy > /dev/null' }
}
```
`promtool check config` may complain that `alerts.yml` isn't at `/etc/prometheus/alerts.yml` when run from the repo. If it does, run `check rules` + `test rules` only, and let the container's startup log validate the config path.

**Gate B7** (ticked by B-Delivery)
- [ ] All three dry-test stages are green, and `promtool test rules` covers the 3 cases
- [ ] With the generator running and someone reviewing: every dashboard panel shows live data within 5 minutes
- [ ] `docker compose restart prometheus` → the graphs keep their history (volume works)
- [ ] Copy a `request_id` from a backend log line, search for it in Grafana → Explore (Loki), and the matching lines from backend-api appear
- [ ] Grafana, Prometheus and Alertmanager open only on `127.0.0.1`, and Grafana requires a login

---

## B8 — Retrain automation (B-Delivery, MLOps phase; needs Team A's A9)

**Goal**: alert → Jenkins → retrain → champion/challenger check → promote or reject, with **no human action**, never two runs at once, and no repeat run for the same problem.

**Trigger chain** (from the earlier design discussion):
1. feedback-service's counters
2. Prometheus computes the ratio
3. the rule fires
4. Alertmanager POSTs the webhook
5. the Generic Webhook Trigger plugin starts `triageiq-retrain`

**`Jenkinsfile.retrain`**
```groovy
pipeline {
  agent { docker { image 'triageiq-ml:latest'; args '--network triageiq_default' } }   // can reach postgres by name
  parameters { choice(name: 'TRIGGER', choices: ['alert', 'manual', 'schedule'], description: 'Why this run started') }
  triggers {
    GenericTrigger(
      genericVariables: [[key: 'status', value: '$.status']],
      tokenCredentialId: 'retrain-webhook-token',
      regexpFilterText: '$status',
      regexpFilterExpression: '^firing$',          // second guard: ignore "resolved" even if Alertmanager sends it
      causeString: 'Alertmanager: $status',
      printContributedVariables: false
    )
  }
  options { disableConcurrentBuilds(); timeout(time: 90, unit: 'MINUTES'); timestamps() }
  environment {
    HOME = "${env.WORKSPACE}"
    OUTCOME = 'failed'
  }
  stages {
    stage('Should run?') {
      steps {
        withCredentials([string(credentialsId: 'postgres-password', variable: 'PGPW')]) {
          script {
            env.DATABASE_URL = "postgresql://triageiq:${PGPW}@postgres:5432/triageiq"
            def rc = sh(script: 'python -m triage_ml.runs should-run --cooldown-minutes 60', returnStatus: true)
            if (rc == 10) { env.SKIP = 'true'; currentBuild.description = 'skipped: cooldown or no new feedback' }
            else if (rc != 0) { error "should-run failed (${rc})" }
          }
        }
      }
    }
    stage('Retrain') {
      when { expression { env.SKIP != 'true' } }
      steps {
        withCredentials([
          string(credentialsId: 'postgres-password', variable: 'PGPW'),
          usernamePassword(credentialsId: 'dagshub', usernameVariable: 'DAGSHUB_USER', passwordVariable: 'DAGSHUB_TOKEN'),
          string(credentialsId: 'hf-token-write', variable: 'HF_TOKEN_WRITE'),
          string(credentialsId: 'hf-token-read',  variable: 'HF_TOKEN_READ')
        ]) {
          script {
            env.DATABASE_URL = "postgresql://triageiq:${PGPW}@postgres:5432/triageiq"
            env.MLFLOW_TRACKING_USERNAME = env.DAGSHUB_USER
            env.MLFLOW_TRACKING_PASSWORD = env.DAGSHUB_TOKEN
            env.RUN_ID = sh(script: "python -m triage_ml.runs start --trigger ${params.TRIGGER} --build ${env.BUILD_TAG}", returnStdout: true).trim()

            def rc = sh(script: 'python -m triage_ml.export_feedback --run-id "$RUN_ID" --out data/feedback/ > snapshot.txt', returnStatus: true)
            if (rc == 4) { env.OUTCOME = 'skipped'; return }
            if (rc != 0) { error "export failed (${rc})" }
            env.SNAPSHOT = readFile('snapshot.txt').trim()

            sh '''
              dvc remote modify origin --local auth basic
              dvc remote modify origin --local user "$DAGSHUB_USER"
              dvc remote modify origin --local password "$DAGSHUB_TOKEN"
              dvc pull data/processed
              dvc add "$SNAPSHOT" && dvc push            # .dvc file is NOT committed: train logs it to MLflow instead
              python -m triage_ml.train --feedback-snapshot "$SNAPSHOT" --run-id "$RUN_ID" --out artifacts/
            '''

            rc = sh(script: 'python -m triage_ml.evaluate --challenger artifacts/ --out eval.json', returnStatus: true)
            if (rc == 3 || rc == 4) { env.OUTCOME = 'rejected'; return }
            if (rc != 0) { error "evaluate failed (${rc})" }

            env.CANDIDATE = sh(script: 'python -m triage_ml.publish --artifacts artifacts/ --run-id "$RUN_ID"', returnStdout: true).trim()
            sh 'python -m triage_ml.promote --revision "$CANDIDATE"'
            env.OUTCOME = 'promoted'
          }
        }
      }
    }
  }
  post {
    always {
      script {
        if (env.RUN_ID) {
          withCredentials([string(credentialsId: 'postgres-password', variable: 'PGPW')]) {
            sh "DATABASE_URL=postgresql://triageiq:\$PGPW@postgres:5432/triageiq python -m triage_ml.runs finish --run-id ${env.RUN_ID} --outcome ${currentBuild.currentResult == 'SUCCESS' ? env.OUTCOME : 'failed'}"
          }
        }
      }
      archiveArtifacts artifacts: 'eval.json, artifacts/metadata.json', allowEmptyArchive: true
      cleanWs()
    }
  }
}
```

**Why the `.dvc` file isn't committed**:
- If the retrain job committed to git, that commit would trigger the CI pipeline, which could deploy and trigger things again.
- Instead, the snapshot's `.dvc` file is logged to MLflow (A9 `train`), and its md5 is stored in `training_runs.feedback_md5`. That's enough to `dvc pull` the exact data later.

**Two Jenkins details that catch everyone**
1. **Triggers and parameters defined in a Jenkinsfile only register after the job's first run.** After merging, run `triageiq-retrain` once by hand with `TRIGGER=manual`. It will exit early at "Should run?", and that's fine.
2. `disableConcurrentBuilds()` **queues** a second trigger rather than dropping it. The queued run then hits the cooldown check and skips itself. This is intended.

**Dry tests**
- The Jenkinsfile linter on `Jenkinsfile.retrain`.
- **Webhook filter test**: post a "resolved" payload directly; **no** build may start:
  ```bash
  curl -s -X POST "http://127.0.0.1:8090/generic-webhook-trigger/invoke?token=$RETRAIN_WEBHOOK_TOKEN" \
       -H 'content-type: application/json' -d '{"status":"resolved"}'
  ```
- **Route test without waiting for real drift**: inject a fake alert into Alertmanager:
  ```bash
  docker compose exec alertmanager amtool alert add ModelErrorRateHigh severity=retrain model_version=test \
       --alertmanager.url=http://127.0.0.1:9093
  ```
  Within ~30s (`group_wait`) a retrain build starts. It should skip itself at "Should run?" if there's no new feedback.

**Gate B8** (ticked by B-Infra + one Team A developer)
- [ ] The "resolved" payload starts no build. The `amtool alert add` injection starts exactly one build
- [ ] Two firing payloads 5 seconds apart → one real run + one run that skips itself
- [ ] **Rejected path**: with new feedback that is all *correct* verdicts (no drift), the run ends `rejected` or `skipped`. The Space version doesn't change, and `training_runs.outcome` is recorded
- [ ] **Promoted path**: after the drift steps in B9, a run ends `promoted`. The UI shows the new model version. `model_versions` shows the old version as `retired` and the new one as `production`
- [ ] Every run has a matching MLflow run (DagsHub) with `feedback_md5` and the champion/challenger scores

---

## B9 — Drift demo, final tuning, final evidence (both Team B developers + one reviewer from Team A)

### B9.1 Drift demo runbook (rehearse at least twice; record the final run)
| Step | Action | Expect |
|---|---|---|
| 0 | Baseline is promoted. Full stack running: `docker compose --profile ops --profile monitoring --profile public up -d` | All healthy. Grafana *TriageIQ Overview* open |
| 1 | `.env`: `TICKET_INTERVAL_SECONDS=10`, `DRIFT_ENABLED=true`, `DRIFT_START_AFTER=30`, `DRIFT_RATIO=0.4` → `docker compose up -d ticket-generator` | Normal tickets for ~5 min |
| 2 | Two reviewers review continuously (open the tunnel URL on two devices) | "Verdicts in last hour" climbs. Accuracy ≈ baseline |
| 3 | Drift starts (ticket 31+) | **Queue mix** panel shifts first. Reviewers keep correcting tickets to *Service Outages and Maintenance* |
| 4 | Once ≥ 30 verdicts on this version and the error ratio passes the threshold for 5 min | Alert `ModelErrorRateHigh` firing (Ops row) |
| 5 | ~30s later | Jenkins `triageiq-retrain` running: export → DVC → train → evaluate → publish → promote |
| 6 | Promote restarts the Space (a few minutes) | "Version currently serving" changes to the new SHA |
| 7 | Reviewers continue | The new version's error ratio falls below the threshold. The held-out queue is now predicted correctly most of the time |
| 8 | Show the evidence | MLflow run, `training_runs` row, `model_versions` statuses, Jenkins stage view, the alert's firing → inactive history |

**Typical durations**: about 40–60 minutes end to end. The slowest parts are collecting 30 verdicts and the Space restart. To shorten a recording, use `TICKET_INTERVAL_SECONDS=5` and three reviewers. **Don't** lower the 30-verdict minimum just for the demo.

**If it doesn't trigger**: check (a) the threshold vs `DRIFT_RATIO` maths in B7.1, (b) that `triageiq_feedback_total` has a `model_version` label in Prometheus, and (c) Alertmanager → *Status* shows the route.

### B9.2 Final resource tuning
After the rehearsals:
1. Re-measure peak memory with `docker stats` for **every** container, including Jenkins during a retrain and Prometheus/Loki after a day of data.
2. Update the compose limits and the kind requests/limits.
3. Add the table to `README.md` with a column "What runs on the demo machine at once" and the total. That total is the number you'd size an AWS instance from (B5 default `t3.large`).

### B9.3 Final MLOps gate (Part 0.2.3)
- [ ] The recorded drift demo shows every step of B9.1
- [ ] A fresh-clone rebuild works: `docker compose down -v`, delete the Jenkins volume, `docker compose --profile ops --profile monitoring up -d --build`, run CI once, run the drift demo again. **No manual configuration anywhere**
- [ ] Rollback works: `python -m triage_ml.promote --rollback` (or the Jenkins equivalent) returns the previous version, and Grafana shows the switch
- [ ] The report includes: architecture diagram (Part 0.1), pipeline stage screenshots, DevSecOps failure evidence (B3.5), the IaC plan output, kind evidence (B6), the alert unit tests, the drift demo video, and the list of `shortcut:` comments as known limitations
