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
    /**
     * Init Fancy Combo-Boxes
     */
    c.initFancyComboBox = function() {
		$('.fancy-combo-box').each(function() {
            var h = $(this).find('input[type=text]').height(),
                w = $(this).find('input[type=text]').width();
		        $(this).find('.entries-overlay').css({'padding-top': h + 5, 'width': w + 30})
        }).live('click', function() {
			$(this).find('.entries-overlay').toggleClass('hidden')
		}).live('mouseleave', function() {
			$(this).find('.entries-overlay').addClass('hidden')
		}).find('.entry').live('click', function(e) {
			var val = $(this).data('val'),
                _$fancyComboBox = $(this).parents('.fancy-combo-box'),
                _$textInput = _$fancyComboBox.find('input:text');
			_$fancyComboBox.data("val", val);
			_$fancyComboBox.find('input:hidden').val(val);
			_$textInput.val($(this).data('text'));
			_$textInput.change();
			$(this).parents('.entries-overlay').addClass('hidden');
			e.stopPropagation();
		});
    };
	$(function() {
        c.initFancyComboBox();
        $('div#lightbox .close, div#lightbox .cancel').click(function() {
            $('div#lightbox').fadeOut()
        })
    });
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

    c.initPayPal = function(trigger, endpoint, data, f1, f2) {
        $.getJSON(endpoint, data, function(response) {
            if (response.error) {
                f1()
            } else {
                c.paypalRedirectURL = response.redirectURL;
                $('#' + trigger).attr('href', response.redirectURL).attr('target', '_blank');
                if (f2) f2()
            }
        })
    };

    w.ikwen = c; /*Creating the namespace ikwen for all this*/
})(window);