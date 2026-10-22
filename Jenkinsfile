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
    stage('Secrets scan') {
      agent { docker { image 'zricethezav/gitleaks:v8.30.1'; args '--entrypoint='; reuseNode true } }
      steps { sh 'gitleaks git --redact --no-banner .' }
    }

    stage('Lint') {
      agent { docker { image 'python:3.11-slim'; reuseNode true } }
      steps {
        sh '''
          python -m venv /tmp/venv && . /tmp/venv/bin/activate
          pip install -q "ruff==0.17.1"
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

    stage('SAST + dependency audit') {
      agent { docker { image 'python:3.11-slim'; reuseNode true } }
      steps {
        sh '''
          python -m venv /tmp/sec && . /tmp/sec/bin/activate
          pip install -q "bandit==1.9.4" "pip-audit==2.10.1"
          bandit -r services ml scripts -x "*/tests/*" -ll -ii           # medium+ severity and confidence fail the build
          # PYSEC-2026-2447: diskcache (via dvc) unsafe pickle; no fixed release, only exploitable by someone who
          # can already write DVC's local cache dir inside the CI/ml container (accepted: Team B, 2026-10-22)
          for r in services/*/requirements.txt ml/requirements.txt; do pip-audit -r "$r" --ignore-vuln PYSEC-2026-2447; done
        '''
      }
    }

    stage('Validate configs') {
      parallel {
        stage('compose') {
          steps { sh 'docker compose --env-file .env.example --profile local-model --profile ops --profile public --profile public-quick config -q' }
        }
        stage('trivy config') {
          agent { docker { image 'aquasec/trivy:0.76.1'; args '--entrypoint='; reuseNode true } }
          steps { sh 'trivy config --exit-code 1 --severity HIGH,CRITICAL --cache-dir /tmp/trivy .' }   // Dockerfiles, Terraform, K8s YAML
        }
        stage('terraform') {
          agent { docker { image 'hashicorp/terraform:1.17.0'; args '--entrypoint='; reuseNode true } }
          steps {
            sh '''
              terraform fmt -check -recursive infra
              for d in infra/aws infra/cloudflare; do
                terraform -chdir=$d init -backend=false -input=false && terraform -chdir=$d validate
              done
            '''
          }
        }
        stage('kubeconform') {
          agent { docker { image 'ghcr.io/yannh/kubeconform:v0.8.0'; args '--entrypoint='; reuseNode true } }
          steps { sh '/kubeconform -strict -summary deploy/k8s/' }
        }
        // promtool/amtool/alloy: B7 (monitoring), not part of this build
      }
    }

    stage('Fetch data') {
      agent { docker { image 'python:3.11'; reuseNode true } }      // full image: DVC needs git
      steps {
        withCredentials([usernamePassword(credentialsId: 'dagshub', usernameVariable: 'DVC_USER', passwordVariable: 'DVC_PASS')]) {
          sh '''
            python -m venv /tmp/dvc && . /tmp/dvc/bin/activate && pip install -q "dvc==3.67.1"
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

    stage('Image scan') {
      agent { docker { image 'aquasec/trivy:0.76.1'; args '--entrypoint= -v /var/run/docker.sock:/var/run/docker.sock'; reuseNode true } }
      steps {
        // shortcut: Trivy re-downloads its vulnerability DB every build, add a cache volume if the stage exceeds ~2 min
        sh '''
          for s in gateway backend-api feedback-service ticket-generator postgres model-service; do
            trivy image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed --cache-dir /tmp/trivy "triageiq-$s:$IMAGE_TAG"
          done
        '''
      }
    }

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
