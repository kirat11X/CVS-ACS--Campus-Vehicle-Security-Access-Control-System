# Entry points for the HITL ANPR pipeline. Anything that costs money or touches AWS is a DRY RUN unless CONFIRM=1.
PY      := .venv/bin/python
ANPR    := .venv/bin/anpr
ROUND   ?= r01
STACK   ?= campus-anpr-hitl
REGION  ?= ap-south-1
TAG     := $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)

.PHONY: help test test-gpu lock round review export docker-build aws-stack docker-push train-aws

help:
	@echo "make test | test-gpu | lock | round ROUND=r01 [ARGS=--oracle] | review ROUND=r02 | export"
	@echo "make docker-build | aws-stack | docker-push | train-aws ROUND=r03   (AWS targets: dry run unless CONFIRM=1)"

test:
	$(PY) -m pytest -q -m "not gpu"

test-gpu:
	$(PY) -m pytest -q -m gpu

lock:
	uv pip freeze --python $(PY) --exclude-editable > requirements.lock

round:
	$(ANPR) run-round --round $(ROUND) $(ARGS)

review:
	$(ANPR) review-app --round $(ROUND)

export:
	$(ANPR) export

docker-build:
	docker build -f aws/Dockerfile -t campus-anpr-hitl:$(TAG) .

aws-stack:
	@test -n "$(BUCKET)" -a -n "$(ALERT_EMAIL)" || { echo "set BUCKET and ALERT_EMAIL"; exit 2; }
	@echo "aws cloudformation deploy --region $(REGION) --stack-name $(STACK) --template-file aws/cloudformation.yaml \\"
	@echo "  --capabilities CAPABILITY_IAM --parameter-overrides BucketName=$(BUCKET) AlertEmail=$(ALERT_EMAIL)"
	@if [ "$(CONFIRM)" = "1" ]; then \
	  aws cloudformation deploy --region $(REGION) --stack-name $(STACK) --template-file aws/cloudformation.yaml \
	    --capabilities CAPABILITY_IAM --parameter-overrides BucketName=$(BUCKET) AlertEmail=$(ALERT_EMAIL) \
	    --tags Project=campus-anpr-hitl; \
	else echo "DRY RUN: add CONFIRM=1 to create the bucket, KMS key (~1 USD/month), role, ECR repo and budget"; fi

docker-push:
	@test -n "$(ECR)" || { echo "set ECR=<account>.dkr.ecr.$(REGION).amazonaws.com/campus-anpr-hitl"; exit 2; }
	@echo "docker tag campus-anpr-hitl:$(TAG) $(ECR):$(TAG) && docker push $(ECR):$(TAG)"
	@if [ "$(CONFIRM)" = "1" ]; then \
	  aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $${ECR%%/*} && \
	  docker tag campus-anpr-hitl:$(TAG) $(ECR):$(TAG) && docker push $(ECR):$(TAG); \
	else echo "DRY RUN: add CONFIRM=1 to push (ECR storage is billed)"; fi

train-aws:
	ROUND=$(ROUND) REGION=$(REGION) CONFIRM=$(CONFIRM) bash aws/launch_train.sh
