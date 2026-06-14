const { describe, it, beforeEach, mock } = require('node:test');
const assert = require('node:assert/strict');

let canRehydrateFetch;
beforeEach(() => {
  delete require.cache[require.resolve('../lib/can-rehydrate-fetch')];
  delete require.cache[require.resolve('../lib/aws-client')];
});

describe('canRehydrateFetch', () => {
  it('fetches all referenced service definitions and runs the linter', async () => {
    const fakeManifest = new Map([
      ['aWSLambda', { key: 'aWSLambda', subType: undefined }],
    ]);
    const fakeDef = {
      serviceCode: 'aWSLambda',
      templates: [{ id: 'lambda-template-1' }],
    };
    const fakeAwsClient = {
      loadManifest: mock.fn(async () => fakeManifest),
      fetchServiceDefinition: mock.fn(async (_m, code) => {
        if (code === 'aWSLambda') return fakeDef;
        return null;
      }),
    };
    require.cache[require.resolve('../lib/aws-client')] = { exports: fakeAwsClient };

    canRehydrateFetch = require('../lib/can-rehydrate-fetch').canRehydrateFetch;

    const r = await canRehydrateFetch({
      savedBlob: {
        services: {
          s1: { serviceCode: 'aWSLambda', estimateFor: 'lambda-template-1', calculationComponents: {} },
        },
      },
    });
    assert.equal(r.status, 'editable');
    assert.equal(fakeAwsClient.loadManifest.mock.calls.length, 1);
    assert.equal(fakeAwsClient.fetchServiceDefinition.mock.calls.length, 1);
  });

  it('also fetches sub-service child definitions', async () => {
    const fakeManifest = new Map([
      ['parent', { key: 'parent', subType: 'subServiceSelector', templates: ['child'] }],
      ['child', { key: 'child', subType: 'subService' }],
    ]);
    const parentDef = {
      serviceCode: 'parent',
      templates: [{ id: 'parentT' }],
      mappingDefinitions: { children: ['child'] },
    };
    const childDef = { serviceCode: 'child', templates: [{ id: 'childT' }] };
    const fetched = [];
    const fakeAwsClient = {
      loadManifest: mock.fn(async () => fakeManifest),
      fetchServiceDefinition: mock.fn(async (_m, code) => {
        fetched.push(code);
        if (code === 'parent') return parentDef;
        if (code === 'child') return childDef;
        return null;
      }),
    };
    require.cache[require.resolve('../lib/aws-client')] = { exports: fakeAwsClient };

    canRehydrateFetch = require('../lib/can-rehydrate-fetch').canRehydrateFetch;

    const r = await canRehydrateFetch({
      savedBlob: {
        services: {
          s1: {
            serviceCode: 'parent',
            estimateFor: 'parentT',
            subServices: [{ serviceCode: 'child', estimateFor: 'childT', calculationComponents: {} }],
          },
        },
      },
    });
    assert.equal(r.status, 'editable');
    assert.deepEqual(fetched.sort(), ['child', 'parent']);
  });

  it('walks services inside groups[*].services', async () => {
    const fakeManifest = new Map([
      ['aWSLambda', { key: 'aWSLambda' }],
    ]);
    const fakeDef = {
      serviceCode: 'aWSLambda',
      templates: [{ id: 'lambda-template-1' }],
    };
    const fetched = [];
    const fakeAwsClient = {
      loadManifest: mock.fn(async () => fakeManifest),
      fetchServiceDefinition: mock.fn(async (_m, code) => {
        fetched.push(code);
        return code === 'aWSLambda' ? fakeDef : null;
      }),
    };
    require.cache[require.resolve('../lib/aws-client')] = { exports: fakeAwsClient };

    canRehydrateFetch = require('../lib/can-rehydrate-fetch').canRehydrateFetch;

    const r = await canRehydrateFetch({
      savedBlob: {
        services: {},
        groups: {
          g1: {
            services: {
              s1: { serviceCode: 'aWSLambda', estimateFor: 'lambda-template-1', calculationComponents: {} },
            },
          },
        },
      },
    });
    assert.equal(r.status, 'editable');
    assert.deepEqual(fetched, ['aWSLambda']);
  });

  it('throws TypeError when savedBlob is null/undefined', async () => {
    canRehydrateFetch = require('../lib/can-rehydrate-fetch').canRehydrateFetch;
    await assert.rejects(
      () => canRehydrateFetch({ savedBlob: null }),
      /requires a savedBlob/
    );
    await assert.rejects(
      () => canRehydrateFetch({}),  // savedBlob undefined
      /requires a savedBlob/
    );
  });
});
