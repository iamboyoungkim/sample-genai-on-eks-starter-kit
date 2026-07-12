#!/usr/bin/env zx

import { fileURLToPath } from "url";
import path from "path";
import fs from "fs";
import handlebars from "handlebars";
import { $ } from "zx";
$.verbose = true;

export const name = "Cost Analysis Agent";
const __filename = fileURLToPath(import.meta.url);
const DIR = path.dirname(__filename);
let BASE_DIR;
let config;
let utils;

export async function init(_BASE_DIR, _config, _utils) {
  BASE_DIR = _BASE_DIR;
  config = _config;
  utils = _utils;
}

const PIPE_FUNCTION_ID = "strands_agents_cost_analysis_agent";
const PIPE_FUNCTION_NAME = "Strands Agents - Cost Analysis Agent";

export async function install() {
  await $`kubectl apply -f ${path.join(DIR, "..", "namespace.yaml")}`;

  // Deploy Terraform (ECR repo + Pod Identity for Bedrock access)
  await utils.terraform.apply(DIR);
  const ecrUrl = await utils.terraform.output(DIR, { outputName: "ecr_repository_url" });

  // Build and push container image
  const { REGION } = process.env;
  const awsAccountId = ecrUrl.split(".")[0];
  await $`aws ecr get-login-password --region ${REGION} | docker login --username AWS --password-stdin ${awsAccountId}.dkr.ecr.${REGION}.amazonaws.com`;

  const IMAGE_URL = `${ecrUrl}:latest`;
  const { useBuildx } = config.docker;
  if (useBuildx) {
    await $`docker buildx build --platform linux/amd64,linux/arm64 -t ${IMAGE_URL} --push ${DIR}`;
  } else {
    await $`docker build -t ${IMAGE_URL} ${DIR}`;
    await $`docker push ${IMAGE_URL}`;
  }

  // Deploy to K8s
  const agentTemplatePath = path.join(DIR, "agent.template.yaml");
  const agentRenderedPath = path.join(DIR, "agent.rendered.yaml");
  const agentTemplateString = fs.readFileSync(agentTemplatePath, "utf8");
  const agentTemplate = handlebars.compile(agentTemplateString);
  const { arch } = config.docker;
  const { LITELLM_API_KEY } = process.env;
  const agentVars = {
    useBuildx,
    arch,
    IMAGE: IMAGE_URL,
    ...config["examples"]["strands-agents"]["cost-analysis-agent"].env,
    LITELLM_BASE_URL: `http://litellm.litellm:4000`,
    LITELLM_API_KEY: LITELLM_API_KEY,
  };
  const result = await $`kubectl get pod -n langfuse -l app=web --ignore-not-found`;
  if (result.stdout.includes("langfuse")) {
    agentVars.LANGFUSE_HOST = "http://langfuse-web.langfuse:3000";
    agentVars.LANGFUSE_PUBLIC_KEY = process.env.LANGFUSE_PUBLIC_KEY;
    agentVars.LANGFUSE_SECRET_KEY = process.env.LANGFUSE_SECRET_KEY;
  }
  fs.writeFileSync(agentRenderedPath, agentTemplate(agentVars));
  await $`kubectl apply -f ${DIR}/agent.rendered.yaml`;

  // Register pipe function in Open WebUI
  const pipeCode = fs.readFileSync(path.join(DIR, "openwebui_pipe_function.py"), "utf8");
  await utils.openwebui.registerAndEnable({ id: PIPE_FUNCTION_ID, name: PIPE_FUNCTION_NAME, code: pipeCode });
}

export async function uninstall() {
  await $`kubectl delete -f ${DIR}/agent.rendered.yaml --ignore-not-found`;
  await utils.openwebui.remove(PIPE_FUNCTION_ID);
  await utils.terraform.destroy(DIR);
}
