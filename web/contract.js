/* ============================================================
   新闻世界地图 · 数据契约校验（地图端）

   与 collector/contract.py 读同一份规格（contract/news-v1.json），
   规则子集两边完全对称：
       type / required / nullable / enum / minLength / items / properties / $ref

   规格随数据快照一起发布到 data/contract.js（window.__NWM_CONTRACT__），
   因此这里校验的永远是「这份数据自带的契约」。
   规格缺失时静默跳过——地图端是消费者，只报告，不越权拒绝渲染。

   用法：
       var errors = window.NWMContract.validate(payload, window.__NWM_CONTRACT__);
   ============================================================ */
(function (global) {
  'use strict';

  function kind(value) {
    if (value === null) return 'null';
    if (Array.isArray(value)) return 'array';
    return typeof value;
  }

  function typeOk(value, typeName) {
    switch (typeName) {
      case 'any': return true;
      case 'string': return typeof value === 'string';
      case 'number': return typeof value === 'number';
      case 'integer': return typeof value === 'number' && value % 1 === 0;
      case 'boolean': return typeof value === 'boolean';
      case 'array': return Array.isArray(value);
      case 'object': return value !== null && typeof value === 'object' && !Array.isArray(value);
      default: return false;
    }
  }

  /** 把 {"$ref": "item"} 展开成本体，并与本层的覆盖项合并。 */
  function resolve(spec, node) {
    if (!node || typeof node !== 'object' || !node.$ref) return node;
    var base = spec[node.$ref] || {};
    var out = {};
    for (var k in base) {
      if (Object.prototype.hasOwnProperty.call(base, k)) out[k] = base[k];
    }
    for (var k2 in node) {
      if (Object.prototype.hasOwnProperty.call(node, k2) && k2 !== '$ref') out[k2] = node[k2];
    }
    return resolve(spec, out);
  }

  function check(value, node, spec, path, errors) {
    if (value === null || value === undefined) {
      if (node.nullable) return;
      errors.push((path || '根') + ': 不允许为 null');
      return;
    }

    var typeName = node.type || 'any';
    if (!typeOk(value, typeName)) {
      errors.push((path || '根') + ': 期望 ' + typeName + '，实际 ' + kind(value));
      return;
    }

    if (node.enum && node.enum.indexOf(value) < 0) {
      errors.push(path + ': 取值 ' + value + ' 不在允许范围 (' + node.enum.join(', ') + ')');
    }

    if (typeName === 'string' && typeof node.minLength === 'number' &&
        value.length < node.minLength) {
      errors.push(path + ': 长度 ' + value.length + ' 小于最小 ' + node.minLength);
    }

    if (typeName === 'array' && node.items) {
      var itemNode = resolve(spec, node.items);
      for (var i = 0; i < value.length; i++) {
        check(value[i], itemNode, spec, path + '[' + i + ']', errors);
      }
    }

    if (typeName === 'object' && node.properties) {
      var props = node.properties;
      // required 是「必填字段名数组」，只出现在对象级规格上。
      var required = node.required || [];
      for (var r = 0; r < required.length; r++) {
        if (!Object.prototype.hasOwnProperty.call(props, required[r])) {
          errors.push((path || '根') + '.' + required[r] + ': 契约声明为必填，但没有定义字段规格');
        }
      }
      for (var name in props) {
        if (!Object.prototype.hasOwnProperty.call(props, name)) continue;
        var sub = resolve(spec, props[name]);
        var child = path ? path + '.' + name : name;
        if (!Object.prototype.hasOwnProperty.call(value, name)) {
          if (required.indexOf(name) >= 0) errors.push(child + ': 缺失（必填）');
          continue;
        }
        check(value[name], sub, spec, child, errors);
      }
    }
  }

  /** 按规格校验一份数据，返回错误列表；空数组表示通过。 */
  function validate(payload, spec) {
    var errors = [];
    if (!payload || !spec || !spec.payload) return errors;
    check(payload, resolve(spec, spec.payload), spec, '', errors);
    return errors;
  }

  global.NWMContract = { validate: validate };
})(window);
