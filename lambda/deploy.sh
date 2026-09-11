#!/usr/bin/env bash
# 예금·적금 이자 계산기를 Lambda + API Gateway(HTTP API)로 배포한다.
# 사전조건: 실행하는 IAM 주체에 lambda:*, apigateway:*, iam:(CreateRole/AttachRolePolicy/PassRole/GetRole) 권한.
#
#   bash lambda/deploy.sh
#
# 출력된 INVOKE_URL 을 frontend/index.html 의 window.LAMBDA_API_URL 에 넣고 재배포한다.
set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-2}"
FN_NAME="finance-interest-calculator"
ROLE_NAME="finance-insight-lambda-role"
API_NAME="finance-insight-http-api"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "▶ 1/6 IAM 역할 준비"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  echo "  역할 생성 완료 — 전파 대기 10초"; sleep 10
fi
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

echo "▶ 2/6 함수 패키징"
TMP_ZIP="$(mktemp -d)/fn.zip"
( cd "$HERE" && zip -q "$TMP_ZIP" interest_calculator.py )

echo "▶ 3/6 Lambda 함수 생성/갱신"
if aws lambda get-function --function-name "$FN_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN_NAME" --zip-file "fileb://$TMP_ZIP" --region "$REGION" >/dev/null
else
  aws lambda create-function --function-name "$FN_NAME" --region "$REGION" \
    --runtime python3.12 --handler interest_calculator.handler \
    --role "$ROLE_ARN" --timeout 10 --memory-size 128 \
    --zip-file "fileb://$TMP_ZIP" >/dev/null
fi
aws lambda wait function-active-v2 --function-name "$FN_NAME" --region "$REGION"
FN_ARN="$(aws lambda get-function --function-name "$FN_NAME" --region "$REGION" --query 'Configuration.FunctionArn' --output text)"

echo "▶ 4/6 HTTP API 생성"
API_ID="$(aws apigatewayv2 get-apis --region "$REGION" --query "Items[?Name=='${API_NAME}'].ApiId | [0]" --output text)"
if [ "$API_ID" = "None" ] || [ -z "$API_ID" ]; then
  API_ID="$(aws apigatewayv2 create-api --region "$REGION" --name "$API_NAME" \
    --protocol-type HTTP \
    --cors-configuration AllowOrigins='*',AllowMethods='POST,OPTIONS',AllowHeaders='content-type' \
    --query ApiId --output text)"
fi

echo "▶ 5/6 통합 + 라우트 연결"
INTEG_ID="$(aws apigatewayv2 create-integration --region "$REGION" --api-id "$API_ID" \
  --integration-type AWS_PROXY --integration-uri "$FN_ARN" \
  --payload-format-version 2.0 --query IntegrationId --output text)"
aws apigatewayv2 create-route --region "$REGION" --api-id "$API_ID" \
  --route-key 'POST /interest' --target "integrations/${INTEG_ID}" >/dev/null || true
aws apigatewayv2 create-stage --region "$REGION" --api-id "$API_ID" \
  --stage-name '$default' --auto-deploy >/dev/null 2>&1 || true

echo "▶ 6/6 Lambda 호출 권한"
aws lambda add-permission --function-name "$FN_NAME" --region "$REGION" \
  --statement-id apigw-invoke --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*/interest" >/dev/null 2>&1 || true

INVOKE_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com"
echo
echo "✅ 배포 완료"
echo "   INVOKE_URL = ${INVOKE_URL}"
echo "   테스트:    curl -s -X POST ${INVOKE_URL}/interest -H 'content-type: application/json' -d '{\"product\":\"deposit\",\"principal\":10000000,\"annual_rate\":3,\"months\":12,\"compounding\":\"compound\"}'"
echo
echo "   → frontend/index.html 의 window.LAMBDA_API_URL 값을 위 INVOKE_URL 로 바꾸고 재배포하세요."
