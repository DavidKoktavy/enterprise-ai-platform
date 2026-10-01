.PHONY: help test lint eval up down demo k8s-render kind-deploy

help:            ## show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

test:            ## unit tests for both services
	cd services/gateway && pytest -q
	cd services/lc-examiner && pytest -q

lint:            ## ruff
	ruff check services eval scripts

eval:            ## UCP 600 golden-set evaluation (quality gate)
	python eval/run_eval.py

up:              ## start local stack (Kafka + gateway + examiner), mock LLM
	docker compose up --build -d

down:
	docker compose down -v

demo:            ## publish sample LC presentations and print examination results
	python scripts/publish_samples.py
	timeout 20 python scripts/consume_results.py || true

k8s-render:      ## render all kustomize overlays
	@for o in base overlays/kind overlays/azure; do echo "--- $$o"; \
	  kubectl kustomize --load-restrictor LoadRestrictionsNone deploy/k8s/$$o >/dev/null && echo ok; done

kind-deploy:     ## build images, load into kind, deploy
	docker build -t ai-gateway:dev services/gateway
	docker build -t lc-examiner:dev services/lc-examiner
	kind load docker-image ai-gateway:dev lc-examiner:dev --name ai-platform
	kubectl kustomize --load-restrictor LoadRestrictionsNone deploy/k8s/overlays/kind | kubectl apply -f -
