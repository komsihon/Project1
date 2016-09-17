/*!
 * Name:        ikwen-util
 * Version:     1.6.2
 * Description: Utility javascript functions and creation of the namespace
 * Author:      Kom Sihon
 * Support:     http://d-krypt.com
 *
 * Depends:
 *      jquery.js http://jquery.org
 *
 * Date: Sat Nov 10 07:55:29 2012 -0500
 */
(function(w) {
    var c = function() {
        return new c.fn.init()
    };
    c.fn = c.prototype = {
        init: function(){return this}
    };
    /**
     * Populate a target FancyComboBox based on a JSON Array of input data
     * fetched from a URL
     * @param endPoint the URL of JSON Array of data
     * @param params additional GET parameters
     * @param targetSelector selector of target FancyComboBox
     * @param value to select after the combo is filled
     */
    c.populateBasedOn = function(endPoint, params, targetSelector, value) {
        var options = '<li class="entry" data-val=""">---------</li>';
        $(targetSelector).next('.spinner').show();
        $.getJSON(endPoint, params, function(data) {
        $(targetSelector).next('.spinner').hide();
            for (var i=0; i<data.length; i++) {
               options += '<li class="entry" data-val="' + data[i].id + '">' + data[i].title + '</li>';
            }
            $(targetSelector).data('val', '').find('input:hidden').val('');
            $(targetSelector + ' .entries').html(options);
            $(targetSelector + ' input:text').val('---------');
            if (value) {
                var text = $(targetSelector + ' .entry[data-val=' + value + ']').text();
                $(targetSelector).data('val', value).find('input:hidden').val(value);
                $(targetSelector + ' input:text').val(text);
            }
        })
    };
    Number.prototype.formatMoney = function(decPlaces, thouSeparator, decSeparator) {
        var n = this,
        decPlaces = isNaN(decPlaces = Math.abs(decPlaces)) ? 0 : decPlaces,
        decSeparator = decSeparator == undefined ? "," : decSeparator, thouSeparator = thouSeparator == undefined ? "." : thouSeparator,
        sign = n < 0 ? "-" : "",
        i = parseInt(n = Math.abs(+n || 0).toFixed(decPlaces)) + "",
        j = (j = i.length) > 3 ? j % 3 : 0;
        return sign + (j ? i.substr(0, j) + thouSeparator : "") + i.substr(j).replace(/(\d{3})(?=\d)/g, "$1" + thouSeparator) + (decPlaces ? decSeparator + Math.abs(n - i).toFixed(decPlaces).slice(2) : "");
    };
    String.prototype.isValidEmail = function() {
        return /^[^\W][a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)*\@[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)*\.[a-zA-Z]{2,4}$/.test(this)
    };
    c.CookieUtil = {
        get: function (name) {
            var cookieName = encodeURIComponent(name) + '=',
            cookieStart = document.cookie.indexOf(cookieName),
            cookieValue = null;
            if (cookieStart > -1) {
                var cookieEnd = document.cookie.indexOf(';', cookieStart);
                if (cookieEnd == -1){
                    cookieEnd = document.cookie.length;
                }
                cookieValue = decodeURIComponent(document.cookie.substring(cookieStart + cookieName.length, cookieEnd));
            }
            return cookieValue;
        },
        set: function (name, value, expires, path, domain, secure) {
            var cookieText = encodeURIComponent(name) + '=' +
            encodeURIComponent(value);
            if (expires instanceof Date) {
                cookieText += '; expires=' + expires.toGMTString();
            }
            if (path) {
                cookieText += '; path=' + path;
            }
            if (domain) {
                cookieText += '; domain=' + domain;
            }
            if (secure) {
                cookieText += '; secure';
            }
            document.cookie = cookieText;
        },
        unset: function (name, path, domain, secure){
            this.set(name, '', new Date(0), path, domain, secure);
        }
    };

    c.showFloatingNotice = function(message, type, duration) {
        $('div#top-notice-ctnr span').removeClass('success failure').html(message).addClass(type);
        if (duration) $('#top-notice-ctnr').fadeIn().delay(duration * 1000).fadeOut();
        else $('#top-notice-ctnr').fadeIn();
    };

    var call = [];
    c.setupSearch = function(inputSelector, resultPanelSelector, descriptors, beforeSearch, afterResults) {
        $('body').on('keyup', inputSelector, function() {
            var q = $(inputSelector).val();
            if (q.length < 2) {
                $(resultPanelSelector).hide();
                call = [];
                return;
            }
            if (beforeSearch) beforeSearch();
            $(resultPanelSelector).find('.empty').hide();
            if (call.length == 0) $(resultPanelSelector).find('.spinner').show();
            $(resultPanelSelector).show();
            for (var i=0; i<descriptors.length; i++) {
                var descriptor = descriptors[i],
                    url = descriptor.endpoint,
                    params = {q: q, start: 0, length: 10, format: 'json'},
                    selector = descriptor.resultTplSelector;
                grabResults(url, params, resultPanelSelector, selector, call.length, afterResults);
                call.push(q);
                // TODO: Manage multiple descriptors and sectioned results
            }
        });
    };

    function grabResults(url, params, resultPanelSelector, resultSelector, callSeqNumber, afterResults) {
        $.getJSON(url, params, function(data) {
            if (data.error) return;
            if (data.length == 0) $(resultPanelSelector).find('.empty').show();
            if (call.length != callSeqNumber + 1) return;
            call = [];
            $(resultPanelSelector).find('.spinner').hide();
            $(resultSelector + ':not(.tpl)').remove();
            for (var i=0; i<data.length; i++) {
                var $tpl = $(resultSelector + '.tpl').clone().removeClass('tpl');
                $tpl = c.genericTemplateFunc($tpl, data[i]);
                $tpl.insertBefore(resultSelector + '.tpl').show();
            }
            if (afterResults) afterResults();
        });

    }

    c.genericTemplateFunc = function($tpl, object, searchTerm) {
        for (var field in object) {
            var value = object[field],
                content = value,
                $fieldElt = $tpl.find('.' + field);
            if (searchTerm) content = value.replace(searchTerm, '<strong>' + searchTerm + '</strong>');
            if ($fieldElt.hasClass('bg-img')) $fieldElt.css('background-image', 'url(' + value + ')');
            else if ($fieldElt.prop('tagName') == 'IMG') $fieldElt.attr('src', value);
            else $fieldElt.html(content);
            if (field == 'url') {
                if (ikwen.URL_KEY && ikwen.URL_RAND) {
                    if (value.indexOf('?') == -1 ) value += '?key=' + ikwen.URL_KEY + '&rand=' + ikwen.URL_RAND;
                    else value += '&key=' + ikwen.URL_KEY + '&rand=' + ikwen.URL_RAND;
                }
                $tpl.find('.target_url').attr('href', value);
            }
            if (typeof value == 'string' || typeof value == 'number') $tpl.data(field, value);
            
            /* Some comon special fields */
            if (field == 'status') $tpl.addClass(value)
        }
        return $tpl
    };

    /**
     * Appends authentication tokens to "href" of all A elements
     * contained in the element with the given selector
     * @param selector a jQuery selector
     */
    c.appendAuthTokens = function(selector) {
        if (ikwen.URL_KEY && ikwen.URL_RAND) {
            $(selector).find('a').each(function () {
                var href = $(this).attr('href');
                if (href.indexOf('?') == -1) href += '?key=' + ikwen.URL_KEY + '&rand=' + ikwen.URL_RAND;
                else href += '&key=' + ikwen.URL_KEY + '&rand=' + ikwen.URL_RAND;
                $(this).attr('href', href);
            })
        }
    };

    w.ikwen = c; /*Creating the namespace ikwen for all this*/
})(window);