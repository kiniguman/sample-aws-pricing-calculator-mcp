const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { transformConfig } = require('../lib/ec2');

describe('EC2 transformConfig', () => {
  it('produces required fields with minimal config', () => {
    const result = transformConfig({});
    assert.equal(result.tenancy.value, 'shared');
    assert.equal(result.selectedOS.value, 'linux');
    assert.equal(result.workloadSelection.value, 'consistent');
    assert.equal(result.instanceType.value, '');
    assert.deepEqual(result.workload.value, { workloadType: 'consistent', data: '1' });
    assert.equal(result.pricingStrategy.value.selectedOption, 'on-demand');
    assert.equal(result.ec2AdvancedPricingMetrics.value, 1);
    assert.equal(result.detailedMonitoringCheckbox.value, false);
    assert.ok(result.dataTransferForEC2, 'should have dataTransferForEC2');
  });

  it('maps quantity to workload data', () => {
    const result = transformConfig({ quantity: 4 });
    assert.equal(result.workload.value.data, '4');
  });

  it('passes through instanceType and OS', () => {
    const result = transformConfig({ instanceType: 'g6.12xlarge', selectedOS: 'windows' });
    assert.equal(result.instanceType.value, 'g6.12xlarge');
    assert.equal(result.selectedOS.value, 'windows');
  });

  it('includes storage when provided', () => {
    const result = transformConfig({ storageType: 'gp3', storageAmount: '100' });
    assert.equal(result.storageType.value, 'Storage General Purpose gp3 GB Mo');
    assert.deepEqual(result.storageAmount, { value: '100', unit: 'gb|NA' });
  });

  it('accepts storage as object', () => {
    const result = transformConfig({ storageAmount: { value: '50', unit: 'gb|NA' } });
    assert.deepEqual(result.storageAmount, { value: '50', unit: 'gb|NA' });
  });

  it('omits storage when not provided', () => {
    const result = transformConfig({});
    assert.equal(result.storageType, undefined);
    assert.equal(result.storageAmount, undefined);
  });
});

describe('EC2 pricing strategy', () => {
  it('parses shorthand: computeSavings1yrNoUpfront', () => {
    const result = transformConfig({ pricingStrategy: 'computeSavings1yrNoUpfront' });
    const ps = result.pricingStrategy.value;
    assert.equal(ps.selectedOption, 'compute-savings');
    assert.equal(ps.term, '1 Year');
    assert.equal(ps.upfrontPayment, 'None');
  });

  it('parses shorthand: instanceSavings3yrAllUpfront', () => {
    const result = transformConfig({ pricingStrategy: 'instanceSavings3yrAllUpfront' });
    const ps = result.pricingStrategy.value;
    assert.equal(ps.selectedOption, 'instance-savings');
    assert.equal(ps.term, '3 Year');
    assert.equal(ps.upfrontPayment, 'All');
  });

  it('parses object format', () => {
    const result = transformConfig({
      pricingStrategy: { model: 'computeSavings', term: '1yr', upfrontPayment: 'None' },
    });
    const ps = result.pricingStrategy.value;
    assert.equal(ps.selectedOption, 'compute-savings');
    assert.equal(ps.term, '1 Year');
  });

  it('remaps reserved to instanceSavings for shared tenancy', () => {
    const result = transformConfig({ pricingStrategy: 'reserved1yrNoUpfront', tenancy: 'shared' });
    assert.equal(result.pricingStrategy.value.selectedOption, 'instance-savings');
  });

  it('remaps convertible to computeSavings for shared tenancy', () => {
    const result = transformConfig({ pricingStrategy: 'convertible1yrNoUpfront', tenancy: 'shared' });
    assert.equal(result.pricingStrategy.value.selectedOption, 'compute-savings');
  });

  it('keeps reserved for dedicated tenancy', () => {
    const result = transformConfig({ pricingStrategy: 'reserved1yrNoUpfront', tenancy: 'dedicated' });
    assert.equal(result.pricingStrategy.value.selectedOption, 'standard');
  });

  it('handles on-demand with utilization', () => {
    const result = transformConfig({ pricingStrategy: 'ondemand', utilization: 75 });
    const ps = result.pricingStrategy.value;
    assert.equal(ps.selectedOption, 'on-demand');
    assert.equal(ps.utilizationValue, '75');
  });

  it('defaults to on-demand when no pricingStrategy', () => {
    const result = transformConfig({});
    assert.equal(result.pricingStrategy.value.selectedOption, 'on-demand');
  });
});
