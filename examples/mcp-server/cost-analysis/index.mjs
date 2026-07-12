#!/usr/bin/env zx

import { fileURLToPath } from "url";
import path from "path";
import fs from "fs";
import handlebars from "handlebars";
import { $ } from "zx";
$.verbose = true;

export const name = "Cost Analysis MCP Server";
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

export async function install() {
  await $`kubectl apply -f ${path.join(DIR, "..", "namespace.yaml")}`;

  // Deploy Terraform (ECR repo + Pod Identity for Cost Explorer access)
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
  const mcpServerTemplatePath = path.join(DIR, "mcp-server.template.yaml");
  const mcpServerRenderedPath = path.join(DIR, "mcp-server.rendered.yaml");
  const mcpServerTemplateString = fs.readFileSync(mcpServerTemplatePath, "utf8");
  const mcpServerTemplate = handlebars.compile(mcpServerTemplateString);
  const { arch } = config.docker;
  const mcpServerVars = {
    useBuildx,
    arch,
    IMAGE: IMAGE_URL,
  };
  fs.writeFileSync(mcpServerRenderedPath, mcpServerTemplate(mcpServerVars));
  await $`kubectl apply -f ${DIR}/mcp-server.rendered.yaml`;
}

export async function uninstall() {
  await $`kubectl delete -f ${DIR}/mcp-server.rendered.yaml --ignore-not-found`;
  await utils.terraform.destroy(DIR);
}
